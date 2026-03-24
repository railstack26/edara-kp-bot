import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BOT_TOKEN      = os.environ.get('BOT_TOKEN')
OPENROUTER_KEY = os.environ.get('OPENROUTER_KEY')
CHAT_ID        = os.environ.get('CHAT_ID')
CNY_RATE       = float(os.environ.get('CNY_RATE', '6.9'))
TELEGRAM_API   = f'https://api.telegram.org/bot{BOT_TOKEN}'

SYSTEM_PROMPT = """Ты - опытный логист компании Edara. Получаешь ответы от китайских партнёров и составляешь КП для клиентов.

КИТАЙСКИЕ ТЕРМИНЫ:
- 国外 / 国外运费 = загранставка (USD)
- 提货费 / 国内提货费 = забор груза в Китае (CNY)
- 线路 = маршрут
- LCL / 铁路拼箱 / 拼箱 = сборный жд (LCL)
- 汽车拼箱 / 散货 = сборное авто (LTL)
- 整箱 / FCL / 40HQ / 40HC / 20GP = полный контейнер (FCL)
- 山口 / 满洲里 = переход Маньчжурия (ZBK)
- 果斯 / 多斯特克 = переход Достык
- 二连浩特 = Эрлянь
- 计费 = расчётный объём
- 特价 = специальная ставка

ГОРОДА КИТАЯ (писать в маршруте ЛАТИНИЦЕЙ):
西安=Xi'an, 青岛=Qingdao, 宁波=Ningbo, 上海=Shanghai, 广州=Guangzhou
成都=Chengdu, 重庆=Chongqing, 深圳=Shenzhen, 长沙=Changsha, 张家港=Zhangjiagang
南通=Nantong, 苏州=Suzhou, 义乌=Yiwu, 宁德=Ningde, 无锡=Wuxi

ГОРОДА НАЗНАЧЕНИЯ (писать на русском):
莫斯科=Москва, 叶卡=Екатеринбург, 沃尔西诺=Ворсино, 谢丽=Селятино, 明斯克=Минск
圣彼得堡=Санкт-Петербург, 托利亚蒂=Тольятти, 萨马拉=Самара

ПРИМЕР МАРШРУТА: Changsha - Маньчжурия - Ворсино (НЕ "Чанша - Маньчжурия - Ворсино")

ОПРЕДЕЛЕНИЕ ТИПА ПЕРЕВОЗКИ:
1. Смотри оригинальный запрос клиента (если передан в контексте)
2. В ответе коллег ищи: 拼箱/LCL/铁路拼箱 = LCL; 汽车/LTL = LTL; 整箱/FCL/40HQ = FCL
3. Есть KG и CBM без типа контейнера = скорее LCL

РАСЧЁТ СТАВКИ (ВАЖНО - считать точно!):

LCL и LTL:
  Итого = загранставка(USD) + 150(маржа Edara) + забор(CNY) / курс_CNY
  Пример: 国外 2271 USD + маржа 150 + 提货费 1800 CNY / 6.9 = 2271+150+261 = 2682 -> 2700 USD

Если ставка USD/CBM (например 132 USD/CBM):
  Итого = (ставка USD/CBM * расч.CBM) + bill_charge + маржа 150 + забор(CNY)/курс
  Пример: 132*13.6 + 150(bill) + 150(маржа) + 2500/6.9 = 1795+150+150+362 = 2457 -> 2500 USD

КРИТИЧЕСКИ ВАЖНО ПРО ЗАБОР (提货费):
  - 提货费 ВСЕГДА добавлять в расчёт - это НЕ входит в загранставку
  - Никогда не писать "забор включён в ставку коллег" - это ошибка
  - Формула: забор_CNY / курс = забор_USD -> добавить к итогу
  - Если коллеги указали свой курс (например 6.96) - использовать его для расчёта забора
  - Пример: 提货费 2500 CNY / 6.96 = 359 USD -> добавить к итогу

FCL:
  Ставка от коллег УЖЕ включает маржу - передавать как есть, 150 USD НЕ добавлять

Округление: всегда вверх до ближайших 50 или 100

КЛИЕНТЫ:
Pontis -> Сергей | BonaFide/Bona -> Максим | Orlan -> Никита
FS-Logistic/FS -> Владислав | Rusmarine -> Дмитрий | Vektura -> Александра

ШАБЛОНЫ КП:

LCL/LTL один вариант:
[Имя],

По запросу [номер], [товар]:

Маршрут: [город CN] - [пограничный переход] - [станция RU]
ETD: [дата]
[вес] KG / [факт.CBM] CBM (Расчётный объём: [расч.CBM] CBM)
Ставка: [итого] USD

Примечания:
1. Расчёт дан для обычного груза без санкционных товаров, при возможности штабелирования. Требуется обязательная проверка кода ТНВЭД перед отправкой.
2. DTHC не включён - оплачивается получателем напрямую.

LCL/LTL несколько вариантов:
[Имя],

предлагаем [N] варианта:

1) [город CN] - [переход] - [станция RU]
   ETD: [дата]
   [вес] KG / [факт.CBM] CBM (Расчётный объём: [расч.CBM] CBM)
   Ставка: [сумма] USD

2) [город CN] - [переход] - [станция RU]
   ETD: [дата]
   [вес] KG / [факт.CBM] CBM (Расчётный объём: [расч.CBM] CBM)
   Ставка: [сумма] USD

Примечания:
1. Расчёт дан для обычного груза без санкционных товаров, при возможности штабелирования. Требуется обязательная проверка кода ТНВЭД перед отправкой.
2. DTHC не включён - оплачивается получателем напрямую.

FCL один вариант:
[Имя],

По запросу [номер], [товар]:

Маршрут: [город CN] - [переход] - [станция RU]
ETD: [дата]
Ставка: [сумма] USD / [тип контейнера]

FCL несколько вариантов:
[Имя],

предлагаем [N] варианта:

1) [город CN] - [переход] - [станция RU]
   ETD: [дата]
   Ставка: [сумма] USD / [тип контейнера]

2) [город CN] - [переход] - [станция RU]
   ETD: [дата]
   Ставка: [сумма] USD / [тип контейнера]

FCL FOB (разбивка FOR + pre carriage):
[Имя],

предлагаем [N] варианта:

1) [город CN] - [переход] - [станция RU]
   ETD: [дата]
   FOR [станция CN] - [станция RU]: [сумма] USD / [тип]
   Pre carriage [город] - [станция]: [сумма] USD
   Итого EXW: [сумма] USD / [тип]

Отказ:
[Имя],

К сожалению, по данному запросу вынуждены отказать - [причина].

ДОПОЛНИТЕЛЬНЫЕ ПРИМЕЧАНИЯ (только если применимо):
- Примечание 3: "Вывоз с Москвы до [город] не включён." - ТОЛЬКО если пункт НЕ Москва
- Примечание 4: "Данная ставка является специальной." - ТОЛЬКО если коллеги написали 特价

ВАЖНО ПРО ПРИМЕЧАНИЕ 1 (ТНВЭД):
  - Если в запросе УЖЕ указан код HS/ТНВЭД - писать примечание 1 БЕЗ фразы про проверку ТНВЭД
  - Если код НЕ указан - оставить фразу: "Требуется обязательная проверка кода ТНВЭД перед отправкой."
  - С кодом: "Расчёт дан для обычного груза без санкционных товаров, при возможности штабелирования."
  - Без кода: "Расчёт дан для обычного груза без санкционных товаров, при возможности штабелирования. Требуется обязательная проверка кода ТНВЭД перед отправкой."

СТРОГО ЗАПРЕЩЕНО добавлять в КП:
  - Упоминания Болгарии или любых других стран если это НЕ указано коллегами
  - СВХ прибытия если НЕ запрошено явно
  - Любые примечания которых нет в шаблонах выше - не придумывай от себя

ПРАВИЛА:
- БЕЗ закрывающей фразы и подписи
- Маршрут: Город отправки - Пограничный переход - Станция прибытия
- Если не хватает данных для расчёта (нет CBM или веса) - запроси их кратко
- Если данные уточнены в reply - используй их и составь КП без повторных вопросов

ФОРМАТ ОТВЕТА:
=== ПЕРЕВОД ===
Тип: [LCL/LTL/FCL]
Маршрут: [...]
ETD: [...]
Расчёт: загран [...] + маржа 150 + забор [...] = итого [...]

=== КП ===
[готовое КП по шаблону]

ЕСЛИ НЕ ХВАТАЕТ ДАННЫХ:
=== ПЕРЕВОД ===
[что понял]

=== УТОЧНИ ===
- [конкретный вопрос 1]
- [конкретный вопрос 2]"""


def send_message(chat_id, text, reply_to=None):
    payload = {'chat_id': chat_id, 'text': text}
    if reply_to:
        payload['reply_to_message_id'] = reply_to
    try:
        requests.post(f'{TELEGRAM_API}/sendMessage', json=payload, timeout=10)
    except Exception as e:
        print(f'sendMessage error: {e}')


def build_messages(chinese_text, original_context='', clarification=''):
    """Строит историю сообщений для Claude с учётом диалога."""
    system = SYSTEM_PROMPT.replace('курс_CNY', str(CNY_RATE))

    # Первое сообщение пользователя
    user_msg = ''
    if original_context:
        user_msg += f'КОНТЕКСТ ЗАПРОСА КЛИЕНТА:\n{original_context}\n\n'
    user_msg += f'ОТВЕТ ОТ КИТАЙСКИХ КОЛЛЕГ:\n{chinese_text}'

    messages = [{'role': 'user', 'content': user_msg}]

    # Если есть уточнение (reply на вопрос бота) - добавляем как продолжение диалога
    if clarification:
        # Добавляем ответ ассистента (он попросил уточнить)
        messages.append({
            'role': 'assistant',
            'content': '=== УТОЧНИ ===\nТребуются дополнительные данные для расчёта.'
        })
        # Добавляем уточнение пользователя
        messages.append({
            'role': 'user',
            'content': f'Уточнение: {clarification}\n\nТеперь составь КП.'
        })

    return system, messages


def call_claude(system, messages):
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
            'messages': [{'role': 'system', 'content': system}] + messages
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

    if chat_id != str(CHAT_ID):
        return jsonify({'ok': True})

    lower = text.lower()
    is_translate = lower.startswith('перевод') or lower.startswith('кп')

    # Проверяем - это reply на предыдущий вопрос бота?
    reply = message.get('reply_to_message', {})
    reply_text = reply.get('text', '') if reply else ''
    is_reply_to_bot = (
        reply and
        reply.get('from', {}).get('is_bot', False) and
        '=== УТОЧНИ ===' in reply_text
    )

    if not is_translate and not is_reply_to_bot:
        return jsonify({'ok': True})

    # Если это reply на вопрос бота — извлекаем контекст из цепочки
    if is_reply_to_bot and not is_translate:
        # Ищем оригинальный текст от коллег в сообщении на которое ответил бот
        original_bot_reply = reply.get('reply_to_message', {})
        original_user_msg  = original_bot_reply.get('text', '') if original_bot_reply else ''

        # Извлекаем текст коллег из оригинального сообщения
        lines = original_user_msg.split('\n')
        chinese_text = '\n'.join(lines[1:]).strip() if lines else original_user_msg

        # Контекст из ещё более раннего сообщения
        original_context = ''
        if original_bot_reply and original_bot_reply.get('reply_to_message'):
            prev = original_bot_reply['reply_to_message']
            original_context = prev.get('text', '')

        clarification = text
        send_message(chat_id, 'Пересчитываю с уточнениями...', reply_to=message_id)

    else:
        # Новый запрос перевод/КП
        lines = text.split('\n')
        chinese_text = '\n'.join(lines[1:]).strip()

        if not chinese_text:
            send_message(chat_id,
                'Вставь текст от коллег после слова перевод или КП',
                reply_to=message_id)
            return jsonify({'ok': True})

        # Контекст из оригинального запроса (если reply на сообщение бота о новом запросе)
        original_context = ''
        if reply_text:
            original_context = reply_text

        clarification = ''
        send_message(chat_id, 'Считаю ставку и готовлю КП...', reply_to=message_id)

    try:
        system, messages = build_messages(chinese_text, original_context, clarification)
        result = call_claude(system, messages)
        send_message(chat_id, result, reply_to=message_id)
    except Exception as e:
        send_message(chat_id, f'Ошибка: {str(e)}', reply_to=message_id)

    return jsonify({'ok': True})


@app.route('/', methods=['GET'])
def index():
    return 'Edara KP Bot is running'


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
