import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ── Переменные окружения (задаются в Railway) ──────────────────
BOT_TOKEN        = os.environ.get('BOT_TOKEN')
OPENROUTER_KEY   = os.environ.get('OPENROUTER_KEY')
CHAT_ID          = os.environ.get('CHAT_ID')   # Dream Team group ID
CNY_RATE         = float(os.environ.get('CNY_RATE', '6.9'))

TELEGRAM_API     = f'https://api.telegram.org/bot{BOT_TOKEN}'

# ── Системный промпт для генерации КП ─────────────────────────
SYSTEM_PROMPT = f"""Ты — логистический ассистент компании Edara.

ЗАДАЧА: Переведи ответ китайских коллег и составь готовое КП для клиента.

КУРС CNY/USD: {CNY_RATE}
МАРЖА LTL/LCL: 150 USD (добавить к ставке коллег)
МАРЖА FCL: уже включена, передавать как есть
DTHC через нас: 150 USD (себестоимость 100 + маржа 50)
Округление: всегда в большую сторону до круглых чисел

КЛИЕНТЫ:
- bonafidegrp.ru / Bona → Максим
- orientlog.ru / Orlan → Никита
- fs-logistic.ru / FS → Владислав
- pontis-expedition.ru / Pontis → Сергей
- rusmarine.ru / Rusmarine → Дмитрий
- vektura.by / Vektura → Александра
- Если клиент неизвестен → [Имя]

ФОРМАТЫ КП:

1. LTL/LCL — один вариант:
[Имя],

По запросу [номер], [товар]:

Маршрут: [город] – [пограничный переход] – [станция прибытия]
ETD: [дата]
[вес] KG / [CBM] CBM (Расчётный объём: [расч. CBM] CBM)
Ставка: [сумма] USD

Примечания:
1. Расчёт дан для обычного груза без санкционных товаров, при возможности штабелирования. Требуется обязательная проверка кода ТНВЭД перед отправкой.
2. DTHC не включён — оплачивается получателем напрямую.
[3. Вывоз с Москвы до [город] не включён в ставку. — если нужно]
[4. Данная ставка является специальной для этого выхода. — если нужно]

2. LTL/LCL — несколько вариантов:
[Имя],

предлагаем [N] варианта:

1) [город] – [переход] – [станция прибытия]
   ETD: [дата]
   [вес] KG / [CBM] CBM (Расчётный объём: [расч. CBM] CBM)
   Ставка: [сумма] USD

2) ...

Примечания:
1. Расчёт дан для обычного груза без санкционных товаров, при возможности штабелирования. Требуется обязательная проверка кода ТНВЭД перед отправкой.
2. DTHC не включён — оплачивается получателем напрямую.

3. FCL — один вариант:
[Имя],

По запросу [номер], [товар]:

Маршрут: [город] – [переход] – [станция прибытия]
ETD: [дата]
Ставка: [сумма] USD / [тип контейнера]

4. FCL — несколько вариантов:
[Имя],

предлагаем [N] варианта:

1) [город] – [переход] – [станция прибытия]
   ETD: [дата]
   Ставка: [сумма] USD / [тип контейнера]

2) ...

5. FCL FOB (с разбивкой):
[Имя],

предлагаем [N] варианта:

1) [город] – [переход] – [станция прибытия]
   ETD: [дата]
   FOR [станция] – [станция]: [сумма] USD / [тип контейнера]
   Pre carriage [город] – [город]: [сумма] USD
   Итого EXW: [сумма] USD / [тип контейнера]

6. Отказ:
[Имя],

К сожалению, по данному запросу вынуждены отказать — [причина].

ПРАВИЛА:
- Определи тип (LTL/LCL/FCL) из контекста
- Посчитай итоговую ставку с маржой
- Если ставка в CNY — переведи по курсу {CNY_RATE} и добавь маржу
- Если данных не хватает — напиши ⚠️ что нужно уточнить
- Если ставка специальная — добавь примечание 4
- БЕЗ закрывающей фразы и подписи

ФОРМАТ ОТВЕТА:
=== ПЕРЕВОД ===
[краткий перевод ответа коллег — 3-5 строк ключевых данных]

=== КП ===
[готовое КП для клиента]"""


# ── Отправка сообщения в Telegram ─────────────────────────────
def send_message(chat_id, text, reply_to=None):
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown'
    }
    if reply_to:
        payload['reply_to_message_id'] = reply_to
    requests.post(f'{TELEGRAM_API}/sendMessage', json=payload)


# ── Генерация КП через Claude (OpenRouter) ────────────────────
def generate_kp(chinese_text, context=''):
    user_content = ''
    if context:
        user_content += f'КОНТЕКСТ ОРИГИНАЛЬНОГО ЗАПРОСА:\n{context}\n\n'
    user_content += f'ОТВЕТ ОТ КИТАЙСКИХ КОЛЛЕГ:\n{chinese_text}'

    response = requests.post(
        'https://openrouter.ai/api/v1/chat/completions',
        headers={
            'Authorization': f'Bearer {OPENROUTER_KEY}',
            'HTTP-Referer': 'https://edara-log.com',
            'X-Title': 'Edara KP Bot',
        },
        json={
            'model': 'anthropic/claude-haiku-4-5',
            'max_tokens': 1500,
            'messages': [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': user_content}
            ]
        }
    )
    data = response.json()
    return data['choices'][0]['message']['content']


# ── Webhook endpoint ───────────────────────────────────────────
@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()

    message = update.get('message') or update.get('edited_message')
    if not message:
        return jsonify({'ok': True})

    chat_id    = str(message['chat']['id'])
    text       = message.get('text', '').strip()
    message_id = message['message_id']

    # Только из нашей группы Dream Team
    if chat_id != str(CHAT_ID):
        return jsonify({'ok': True})

    # Проверяем ключевые слова
    lower = text.lower()
    if not (lower.startswith('перевод') or lower.startswith('кп')):
        return jsonify({'ok': True})

    # Извлекаем текст от китайских коллег (всё после первой строки)
    lines = text.split('\n')
    chinese_text = '\n'.join(lines[1:]).strip()

    if not chinese_text:
        send_message(chat_id,
            '⚠️ Пришли текст от китайских коллег после слова «перевод» или «КП»',
            reply_to=message_id)
        return jsonify({'ok': True})

    # Контекст из оригинального сообщения бота (если reply)
    context = ''
    reply = message.get('reply_to_message')
    if reply and reply.get('text'):
        context = reply['text']

    # Отправляем промежуточное сообщение
    send_message(chat_id, '⏳ Обрабатываю ответ от коллег...', reply_to=message_id)

    # Генерируем КП
    try:
        result = generate_kp(chinese_text, context)
        send_message(chat_id, '📊 ' + result, reply_to=message_id)
    except Exception as e:
        send_message(chat_id, f'⚠️ Ошибка: {str(e)}', reply_to=message_id)

    return jsonify({'ok': True})


# ── Health check ───────────────────────────────────────────────
@app.route('/', methods=['GET'])
def index():
    return 'Edara KP Bot is running ✅'


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
