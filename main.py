import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BOT_TOKEN      = os.environ.get('BOT_TOKEN')
OPENROUTER_KEY = os.environ.get('OPENROUTER_KEY')
CHAT_ID        = os.environ.get('CHAT_ID')
CNY_RATE       = float(os.environ.get('CNY_RATE', '6.9'))

TELEGRAM_API   = f'https://api.telegram.org/bot{BOT_TOKEN}'

SYSTEM_PROMPT = f"""Ты — логистический ассистент компании Edara. Переведи ответ китайских коллег и составь КП для клиента.

КУРС CNY/USD: {CNY_RATE}

РАСЧЁТ СТАВКИ:
- LTL (сборное авто) / LCL (сборное жд): итоговая ставка = загранставка USD + маржа 150 USD + (забор CNY ÷ {CNY_RATE})
- FCL (полный контейнер): ставка коллег уже включает маржу — передавать как есть
- DTHC через нас: добавить 150 USD (себестоимость 100 + маржа 50)
- Все суммы округлять в большую сторону до круглых чисел

ОПРЕДЕЛЕНИЕ ТИПА:
- 拼箱 / LCL / сборный / сборная жд / 铁路拼箱 → LCL (сборное жд)
- 散货 / сборное авто / LTL → LTL (сборное авто)  
- 整箱 / 40HQ / 40HC / 20GP / полный контейнер / FCL → FCL
- Смотри на контекст из оригинального запроса если он есть

КЛИЕНТЫ И ОБРАЩЕНИЯ:
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

Маршрут: [город отправки] – [пограничный переход] – [станция прибытия]
ETD: [дата]
[вес] KG / [CBM] CBM (Расчётный объём: [расч. CBM] CBM)
Ставка: [итоговая сумма с маржой] USD

Примечания:
1. Расчёт дан для обычного груза без санкционных товаров, при возможности штабелирования. Требуется обязательная проверка кода ТНВЭД перед отправкой.
2. DTHC не включён — оплачивается получателем напрямую.

2. LTL/LCL — несколько вариантов:
[Имя],

предлагаем [N] варианта:

1) [город] – [переход] – [станция прибытия]
   ETD: [дата]
   [вес] KG / [CBM] CBM (Расчётный объём: [расч. CBM] CBM)
   Ставка: [сумма] USD

2) [город] – [переход] – [станция прибытия]
   ETD: [дата]
   [вес] KG / [CBM] CBM (Расчётный объём: [расч. CBM] CBM)
   Ставка: [сумма] USD

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

5. FCL FOB (с разбивкой FOR + pre carriage):
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
- Определи тип перевозки из контекста (особенно из оригинального запроса)
- Для LTL/LCL ОБЯЗАТЕЛЬНО посчитай: загранставка + 150 USD маржа + (забор CNY ÷ {CNY_RATE})
- Пример расчёта LCL: загран 2271 USD + маржа 150 + забор (1800 CNY ÷ 6.9 = 261 USD) = 2682 USD → округляем → 2700 USD
- Для FCL ставку коллег передавай как есть без добавления маржи
- Примечание "специальная ставка" добавляй ТОЛЬКО если коллеги явно написали что ставка специальная
- Примечание "вывоз с Москвы" добавляй ТОЛЬКО если пункт назначения не Москва
- БЕЗ закрывающей фразы и подписи
- Если данных не хватает — напиши ⚠️ что нужно уточнить

ФОРМАТ ОТВЕТА (строго):
=== ПЕРЕВОД ===
[краткий перевод: маршрут, ETD, ставка загран, забор, расчёт итога]

=== КП ===
[готовое КП]"""


def send_message(chat_id, text, reply_to=None):
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown'
    }
    if reply_to:
        payload['reply_to_message_id'] = reply_to
    try:
        requests.post(f'{TELEGRAM_API}/sendMessage', json=payload, timeout=10)
    except Exception as e:
        print(f'sendMessage error: {e}')


def generate_kp(chinese_text, context=''):
    user_content = ''
    if context:
        user_content += f'КОНТЕКСТ ОРИГИНАЛЬНОГО ЗАПРОСА КЛИЕНТА:\n{context}\n\n'
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
        },
        timeout=30
    )
    data = response.json()
    return data['choices'][0]['message']['content']


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

    lower = text.lower()
    if not (lower.startswith('перевод') or lower.startswith('кп')):
        return jsonify({'ok': True})

    # Текст от коллег — всё после первой строки
    lines = text.split('\n')
    chinese_text = '\n'.join(lines[1:]).strip()

    if not chinese_text:
        send_message(chat_id,
            '⚠️ Вставь текст от коллег после слова «перевод» или «КП»',
            reply_to=message_id)
        return jsonify({'ok': True})

    # Контекст из оригинального сообщения бота (если reply)
    context = ''
    reply = message.get('reply_to_message')
    if reply and reply.get('text'):
        context = reply['text']

    send_message(chat_id, '⏳ Считаю ставку и готовлю КП...', reply_to=message_id)

    try:
        result = generate_kp(chinese_text, context)
        send_message(chat_id, '📊 ' + result, reply_to=message_id)
    except Exception as e:
        send_message(chat_id, f'⚠️ Ошибка: {str(e)}', reply_to=message_id)

    return jsonify({'ok': True})


@app.route('/', methods=['GET'])
def index():
    return 'Edara KP Bot is running ✅'


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
