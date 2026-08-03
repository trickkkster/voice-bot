# 🎤 Голосовой Telegram бот — Станислав (Память + Поиск)
import requests
import urllib3
import ssl
import os
import json
import time
from datetime import datetime

urllib3.disable_warnings()

# ===== ТВОИ КЛЮЧИ (берутся из переменных окружения Railway) =====
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
# ==================================================================

MEMORY_FILE = "bot_memory.json"
MAX_HISTORY = 20

def make_session():
    s = requests.Session()
    s.verify = False
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers("DEFAULT@SECLEVEL=1")

    class SSLAdapter(requests.adapters.HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            kwargs["ssl_context"] = ctx
            return super().init_poolmanager(*args, **kwargs)

    s.mount("https://", SSLAdapter(max_retries=3))
    return s

session = make_session()

def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {
        "user_name": None,
        "user_facts": [],
        "conversation_history": [],
        "first_seen": datetime.now().strftime("%d.%m.%Y")
    }

def save_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)

memory = load_memory()

def send_voice(chat_id, text):
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang="ru")
        tts.save("response.mp3")
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVoice"
        with open("response.mp3", "rb") as audio:
            files = {"voice": audio}
            data = {"chat_id": chat_id}
            session.post(url, data=data, files=files, timeout=30)
        if os.path.exists("response.mp3"):
            os.remove("response.mp3")
        return True
    except Exception as e:
        print(f"Ошибка озвучки: {e}")
        return False

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        session.post(url, json={"chat_id": chat_id, "text": text}, timeout=20)
    except Exception as e:
        print(f"Ошибка отправки: {e}")

def download_voice(file_id):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}"
        response = session.get(url, timeout=15)
        file_path = response.json()["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        audio = session.get(file_url, timeout=20)
        with open("voice.ogg", "wb") as f:
            f.write(audio.content)
        return "voice.ogg"
    except Exception as e:
        print(f"Ошибка скачивания: {e}")
        return None

def extract_facts(text):
    global memory
    text_lower = text.lower()
    if "меня зовут" in text_lower:
        name = text_lower.split("меня зовут")[-1].strip().split()[0]
        memory["user_name"] = name.capitalize()
    keywords = ["я люблю", "я работаю", "я живу", "мне нравится", "я занимаюсь"]
    for kw in keywords:
        if kw in text_lower:
            fact = text_lower.split(kw)[-1].strip()[:100]
            full_fact = f"{kw} {fact}"
            if full_fact not in memory["user_facts"]:
                memory["user_facts"].append(full_fact)
                if len(memory["user_facts"]) > 15:
                    memory["user_facts"] = memory["user_facts"][-15:]

def download_photo(file_id):
    """Скачиваем фото из Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}"
        response = session.get(url, timeout=15)
        file_path = response.json()["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        photo_data = session.get(file_url, timeout=20)
        with open("photo.jpg", "wb") as f:
            f.write(photo_data.content)
        return "photo.jpg"
    except Exception as e:
        print(f"❌ Ошибка скачивания фото: {e}")
        return None

def analyze_photo(file_path, question="Что изображено на этой картинке?"):
    """Анализируем фото через Groq Vision"""
    try:
        import base64
        with open(file_path, "rb") as img:
            img_base64 = base64.b64encode(img.read()).decode("utf-8")

        vision_session = make_session()
        response = vision_session.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "qwen/qwen3.6-27b",
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Отвечай на русском языке кратко. {question}"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
                    ]
                }],
                "max_tokens": 300
            },
            timeout=30
        )
        result = response.json()
        print(f"DEBUG vision: {result}")
        if "choices" in result:
            return result["choices"][0]["message"]["content"]
        elif "error" in result:
            return f"Не смог обработать фото: {result['error'].get('message', '')}"
        return "Не удалось проанализировать фото"
    except Exception as e:
        print(f"❌ Ошибка анализа фото: {e}")
        return "Извините, ошибка при обработке фото"

# 🔍 ПОИСК В ИНТЕРНЕТЕ
def needs_search(question):
    """Определяем нужен ли поиск для этого вопроса"""
    search_triggers = [
        "сегодня", "сейчас", "последние", "новости", "курс", "погода",
        "текущий", "актуальн", "кто такой", "что такое", "когда будет",
        "цена", "стоимость", "что происходит", "последняя версия"
    ]
    question_lower = question.lower()
    return any(trigger in question_lower for trigger in search_triggers)

def get_currency():
    """Получаем курс валют"""
    try:
        curr_session = make_session()
        response = curr_session.get("https://open.er-api.com/v6/latest/RUB", timeout=15)
        data = response.json()
        rates = data.get("rates", {})
        result = []
        if "USD" in rates and rates["USD"] > 0:
            result.append(f"Доллар: {1/rates['USD']:.2f} руб")
        if "EUR" in rates and rates["EUR"] > 0:
            result.append(f"Евро: {1/rates['EUR']:.2f} руб")
        if "CNY" in rates and rates["CNY"] > 0:
            result.append(f"Юань: {1/rates['CNY']:.2f} руб")
        return ", ".join(result) if result else None
    except Exception as e:
        print(f"❌ Ошибка валют: {e}")
        return None

def get_crypto_price(coin="bitcoin"):
    """Получаем реальную цену криптовалюты через CoinGecko"""
    try:
        crypto_session = make_session()
        response = crypto_session.get(
            f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd,rub",
            timeout=15
        )
        data = response.json()
        if coin in data:
            usd = data[coin].get("usd", "?")
            rub = data[coin].get("rub", "?")
            return f"{coin}: ${usd} ({rub} руб)"
        return None
    except Exception as e:
        print(f"❌ ОШИБКА крипты: {type(e).__name__}: {e}")
        return None

REMINDERS_FILE = "reminders.json"

def load_reminders():
    if os.path.exists(REMINDERS_FILE):
        try:
            with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return []

def save_reminders(reminders):
    with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(reminders, f, ensure_ascii=False, indent=2)

reminders = load_reminders()

def add_reminder(text, chat_id):
    """Добавляем напоминание"""
    global reminders
    reminders.append({
        "text": text,
        "chat_id": chat_id,
        "created": datetime.now().isoformat(),
        "done": False
    })
    save_reminders(reminders)

def check_reminders():
    """Проверяем есть ли новые невыполненные напоминания для показа"""
    pending = [r for r in reminders if not r.get("done")]
    return pending

def classify_intent(question):
    """AI сам определяет намерение пользователя"""
    try:
        classify_session = make_session()
        response = classify_session.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "openai/gpt-oss-20b",
                "messages": [{
                    "role": "user",
                    "content": f"""Определи намерение пользователя. Ответь ТОЛЬКО одним словом без пояснений:
- "weather" если спрашивает про погоду, температуру, дождь, солнце на улице
- "crypto_bitcoin" если про биткоин
- "crypto_ethereum" если про эфириум
- "crypto_ton" если про TON/тонкоин
- "currency" если спрашивает про курс доллара, евро, юаня
- "math" если нужно что-то посчитать/вычислить
- "reminder" если просит напомнить о чём-то, поставить напоминание, будильник
- "translate" если просит перевести текст на другой язык
- "write_text" если просит написать письмо, пост, сообщение, текст для чего-то
- "search" если нужна общая актуальная информация из интернета, новости
- "chat" если это обычный разговор, не требующий данных

Вопрос: "{question}"

Ответь одним словом:"""
                }],
                "max_tokens": 10,
                "temperature": 0
            },
            timeout=10
        )
        result = response.json()
        if "choices" in result:
            intent = result["choices"][0]["message"]["content"].strip().lower()
            print(f"🎯 Определено намерение: {intent}")
            return intent
        return "chat"
    except Exception as e:
        print(f"❌ Ошибка классификации: {e}")
        return "chat"

def calculate(expression):
    """Простой калькулятор для математических выражений"""
    try:
        calc_session = make_session()
        response = calc_session.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "openai/gpt-oss-120b",
                "messages": [{
                    "role": "user",
                    "content": f"Реши математическую задачу и ответь ТОЛЬКО числом или коротким результатом, без объяснений: {expression}"
                }],
                "max_tokens": 50,
                "temperature": 0
            },
            timeout=15
        )
        result = response.json()
        if "choices" in result:
            return result["choices"][0]["message"]["content"].strip()
        return None
    except Exception as e:
        print(f"❌ Ошибка вычисления: {e}")
        return None

def get_weather(city="Краснодар"):
    """Получаем реальную погоду через бесплатный API"""
    try:
        weather_session = make_session()
        response = weather_session.get(
            f"https://wttr.in/{city}?format=%C+%t+влажность:%h+ветер:%w&lang=ru",
            timeout=15
        )
        print(f"DEBUG погода статус: {response.status_code}")
        print(f"DEBUG погода текст: {response.text[:200]}")
        return response.text.strip()
    except Exception as e:
        print(f"❌ ОШИБКА погоды: {type(e).__name__}: {e}")
        return None

def search_web(query):
    """Ищем информацию через DuckDuckGo"""
    try:
        search_session = make_session()
        response = search_session.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1},
            timeout=15
        )
        print(f"DEBUG поиск статус: {response.status_code}")
        data = response.json()
        print(f"DEBUG поиск данные: {str(data)[:200]}")

        result_text = ""
        if data.get("Abstract"):
            result_text = data["Abstract"]
        elif data.get("RelatedTopics"):
            topics = data["RelatedTopics"][:3]
            result_text = " ".join([t.get("Text", "") for t in topics if "Text" in t])

        return result_text if result_text else None
    except Exception as e:
        print(f"❌ ОШИБКА поиска: {type(e).__name__}: {e}")
        return None

def ask_groq(question):
    """Отправляем вопрос с учётом памяти и поиска"""
    global memory

    extract_facts(question)
    memory["conversation_history"].append({"role": "user", "content": question})

    # 🎯 AI определяет намерение пользователя
    search_result = None
    intent = classify_intent(question)

    if intent == "weather":
        print(f"🌤 Проверяю погоду...")
        search_result = get_weather("Краснодар")
        if search_result:
            print(f"✅ Погода: {search_result}")
    elif intent == "crypto_bitcoin":
        print(f"💰 Проверяю курс биткоина...")
        search_result = get_crypto_price("bitcoin")
    elif intent == "crypto_ethereum":
        print(f"💰 Проверяю курс эфириума...")
        search_result = get_crypto_price("ethereum")
    elif intent == "crypto_ton":
        print(f"💰 Проверяю курс TON...")
        search_result = get_crypto_price("the-open-network")
    elif intent == "currency":
        print(f"💱 Проверяю курс валют...")
        search_result = get_currency()
    elif intent == "reminder":
        print(f"⏰ Сохраняю напоминание...")
        add_reminder(question, CHAT_ID)
        search_result = "Напоминание сохранено! Скажи мне 'мои напоминания' чтобы посмотреть список."
    elif intent == "math":
        print(f"🧮 Считаю...")
        calc_result = calculate(question)
        if calc_result:
            search_result = f"Результат вычисления: {calc_result}"
    elif intent == "search":
        print(f"🔍 Ищу информацию по запросу: {question}")
        search_result = search_web(question)
        if search_result:
            print(f"✅ Найдено: {search_result[:100]}...")

    system_prompt = "Ты дружелюбный голосовой ассистент по имени Trickster. Отвечай понятно на русском языке."

    if intent in ("translate", "write_text"):
        system_prompt += " Для этой задачи можешь дать более развёрнутый ответ, если это необходимо для качества перевода или текста."
    else:
        system_prompt += " Отвечай кратко — максимум 3 предложения."

    if memory["user_name"]:
        system_prompt += f" Пользователя зовут {memory['user_name']}, обращайся к нему по имени иногда."

    if memory["user_facts"]:
        facts_text = "; ".join(memory["user_facts"][-5:])
        system_prompt += f" Вот что ты знаешь о пользователе: {facts_text}."

    if search_result:
        system_prompt += f" У тебя есть свежая информация из интернета по этому вопросу: {search_result}. Используй её в ответе."

    try:
        messages = [{"role": "system", "content": system_prompt}] + memory["conversation_history"][-MAX_HISTORY:]

        groq_session = make_session()
        response = groq_session.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "openai/gpt-oss-120b",
                "messages": messages,
                "max_tokens": 300
            },
            timeout=30
        )
        result = response.json()
        print(f"DEBUG: {result}")

        if "choices" in result:
            answer = result["choices"][0]["message"]["content"]
            memory["conversation_history"].append({"role": "assistant", "content": answer})
            if len(memory["conversation_history"]) > MAX_HISTORY:
                memory["conversation_history"] = memory["conversation_history"][-MAX_HISTORY:]
            save_memory(memory)
            return answer
        elif "error" in result:
            return f"Ошибка: {result['error'].get('message', 'неизвестная')}"
        return "Не могу ответить"
    except Exception as e:
        print(f"Ошибка Groq: {e}")
        return "Извините, ошибка соединения"

def get_updates(offset=0):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}&timeout=10"
    try:
        response = session.get(url, timeout=15)
        return response.json().get("result", [])
    except:
        return []

print("🤖 Голосовой бот запущен (Память + Поиск)!")
print(f"📁 Память загружена: {len(memory['conversation_history'])} сообщений")
if memory["user_name"]:
    print(f"👤 Помню пользователя: {memory['user_name']}")
print("Нажми Ctrl+C чтобы остановить")

greeting = "🎤 Голосовой бот запущен!\n\n"
if memory["user_name"]:
    greeting += f"Привет снова, {memory['user_name']}! Я помню наш разговор. 🧠\n\n"
else:
    greeting += "Я запоминаю всё что ты рассказываешь и умею искать в интернете! 🧠🔍\n\n"
greeting += "Отправь мне:\n• Голосовое сообщение 🎙\n• Или текстовый вопрос ✍️"

send_message(CHAT_ID, greeting)

offset = 0
while True:
    updates = get_updates(offset)

    for update in updates:
        offset = update["update_id"] + 1
        message = update.get("message", {})
        chat_id = message.get("chat", {}).get("id")

        if "photo" in message:
            print("📸 Получено фото!")
            photos = message["photo"]
            file_id = photos[-1]["file_id"]  # Берём самое большое разрешение
            file_path = download_photo(file_id)

            if file_path:
                caption = message.get("caption", "Что изображено на этой картинке?")
                answer = analyze_photo(file_path, caption)
                send_message(chat_id, f"🤖 {answer}")
                if os.path.exists(file_path):
                    os.remove(file_path)

        elif "voice" in message:
            print("🎤 Получено голосовое!")
            file_id = message["voice"]["file_id"]
            file_path = download_voice(file_id)

            if file_path:
                try:
                    import speech_recognition as sr
                    import subprocess
                    subprocess.run(
                        ["ffmpeg", "-i", "voice.ogg", "-ar", "16000", "voice.wav", "-y"],
                        capture_output=True
                    )
                    recognizer = sr.Recognizer()
                    with sr.AudioFile("voice.wav") as source:
                        audio = recognizer.record(source)
                        text = recognizer.recognize_google(audio, language="ru-RU")

                    print(f"👤 Распознано: {text}")
                    answer = ask_groq(text)
                    send_voice(chat_id, answer)

                    for f in ["voice.ogg", "voice.wav"]:
                        if os.path.exists(f):
                            os.remove(f)
                except Exception as e:
                    print(f"Ошибка: {e}")
                    send_message(chat_id, "❌ Не смог распознать. Напиши текстом!")

        elif "text" in message:
            text = message["text"]
            if text == "/start":
                send_message(chat_id, greeting)
            elif text == "/clear":
                memory["conversation_history"] = []
                save_memory(memory)
                send_message(chat_id, "🧹 История очищена! Но я помню факты о тебе.")
            elif text == "/forget":
                memory = {"user_name": None, "user_facts": [], "conversation_history": [], "first_seen": datetime.now().strftime("%d.%m.%Y")}
                save_memory(memory)
                send_message(chat_id, "🗑 Я всё забыл! Начинаем с чистого листа.")
            elif text == "/memory":
                facts = "\n".join([f"• {f}" for f in memory["user_facts"]]) if memory["user_facts"] else "Пока ничего не знаю"
                name = memory["user_name"] or "не знаю"
                send_message(chat_id, f"🧠 Помню:\n\nИмя: {name}\n\nФакты:\n{facts}")
            elif text == "/reminders" or "мои напоминания" in text.lower():
                pending = check_reminders()
                if pending:
                    rem_text = "\n".join([f"⏰ {r['text']}" for r in pending])
                    send_message(chat_id, f"📋 Твои напоминания:\n\n{rem_text}")
                else:
                    send_message(chat_id, "📋 У тебя пока нет напоминаний")
            else:
                print(f"💬 Текст: {text}")
                answer = ask_groq(text)
                send_message(chat_id, f"🤖 {answer}")

    time.sleep(1)
