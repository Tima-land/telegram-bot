import logging
import json
import os
import shutil
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler
)

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
ROLE_SELECTION, REPORT_PHOTO, REPORT_TEXT, UPLOAD_NEXT_LESSON = range(4)

# Инициализация данных
DATA_FILE = 'b1ot_data.json'
LESSONS_DIR = 'le1ssons'
REPORTS_DIR = 're1ports'

# Клавиатуры
MOTHER_KEYBOARD = ReplyKeyboardMarkup(
    [["📝 Создать урок", "📋 Список уроков", "🔔 Напомнить о задании"]],
    resize_keyboard=True,
    one_time_keyboard=False
)

SON_KEYBOARD = ReplyKeyboardMarkup(
    [["🎬 Получить урок", "📝 Сдать отчет"]],
    resize_keyboard=True,
    one_time_keyboard=False
)


class BotData:
    @staticmethod
    def reset():
        """Сбрасывает все данные бота"""
        data = {
            'users': {},
            'lessons': {},
            'reports': {},
            'lesson_counter': 1
        }
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)

        for folder in [LESSONS_DIR, REPORTS_DIR]:
            if os.path.exists(folder):
                shutil.rmtree(folder)
            os.makedirs(folder)

        logger.info("Все данные сброшены")

    @staticmethod
    def load():
        """Загружает данные из файла или создает новые"""
        if not os.path.exists(DATA_FILE):
            BotData.reset()
        with open(DATA_FILE, 'r') as f:
            return json.load(f)

    @staticmethod
    def save(data):
        """Сохраняет данные в файл"""
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало работы с ботом, выбор роли"""
    data = BotData.load()
    user_id = str(update.effective_user.id)

    if user_id in data['users']:
        role = data['users'][user_id]['role']
        if role == 'mother':
            await update.message.reply_text(
                "Вы зарегистрированы как 👩 Мать",
                reply_markup=MOTHER_KEYBOARD
            )
        else:
            await update.message.reply_text(
                "Вы зарегистрированы как 👦 Сын",
                reply_markup=SON_KEYBOARD
            )
            await show_son_status(update.message, data, user_id)
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("👩 Мать", callback_data='mother')],
        [InlineKeyboardButton("👦 Сын", callback_data='son')]
    ]
    await update.message.reply_text(
        "Выберите вашу роль:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ROLE_SELECTION


async def show_son_status(message, data, user_id):
    """Показывает статус для сына"""
    current_lesson = data['users'][user_id].get('current_lesson', 1)
    lesson_key = str(current_lesson)

    if lesson_key in data['lessons']:
        message_text = "Урок доступен! Используйте кнопку '🎬 Получить урок'"
    else:
        message_text = f"Урок #{current_lesson} еще не загружен."

    await message.reply_text(
        f"👦 Сын\nТекущий урок: #{current_lesson}\n{message_text}",
        reply_markup=SON_KEYBOARD
    )


async def role_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора роли"""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    role = query.data
    data = BotData.load()

    data['users'][user_id] = {
        'role': role,
        'current_lesson': 1,
        'name': query.from_user.full_name
    }
    BotData.save(data)

    if role == 'mother':
        await query.message.reply_text(
            "Вы выбрали роль: 👩 Мать\n\n"
            "Используйте кнопки ниже для управления:",
            reply_markup=MOTHER_KEYBOARD
        )
    else:
        await query.message.reply_text(
            "Вы выбрали роль: 👦 Сын\n\n"
            "Используйте кнопки ниже для управления:",
            reply_markup=SON_KEYBOARD
        )
        await show_son_status(query.message, data, user_id)

    return ConversationHandler.END


async def request_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Создание нового урока"""
    data = BotData.load()
    user_id = str(update.effective_user.id)

    if data['users'].get(user_id, {}).get('role') != 'mother':
        await update.message.reply_text("❌ Только матери могут создавать уроки!", reply_markup=MOTHER_KEYBOARD)
        return ConversationHandler.END

    lesson_number = data['lesson_counter']
    data['lesson_counter'] += 1
    BotData.save(data)

    lesson_dir = os.path.join(LESSONS_DIR, str(lesson_number))
    os.makedirs(lesson_dir, exist_ok=True)

    await update.message.reply_text(
        f"📝 Создан урок #{lesson_number}\n"
        "Теперь загрузите материалы для этого урока (видео или фото):",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data['uploading_lesson'] = lesson_number
    return UPLOAD_NEXT_LESSON


async def handle_lesson_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка загружаемых материалов урока"""
    if not (update.message.video or update.message.photo):
        await update.message.reply_text("❌ Пожалуйста, отправьте видео или фото")
        return UPLOAD_NEXT_LESSON

    data = BotData.load()
    lesson_number = context.user_data.get('uploading_lesson')

    if not lesson_number:
        await update.message.reply_text("❌ Ошибка: номер урока не найден", reply_markup=MOTHER_KEYBOARD)
        return ConversationHandler.END

    # Определяем тип и скачиваем файл
    lesson_dir = os.path.join(LESSONS_DIR, str(lesson_number))
    file_path = None

    if update.message.video:
        video = update.message.video
        file_path = os.path.join(lesson_dir, 'lesson.mp4')
        await (await video.get_file()).download_to_drive(file_path)
        media_type = 'video'
    else:
        photo = update.message.photo[-1]  # Берем самое качественное фото
        file_path = os.path.join(lesson_dir, 'lesson.jpg')
        await (await photo.get_file()).download_to_drive(file_path)
        media_type = 'photo'

    # Сохраняем информацию об уроке
    data['lessons'][str(lesson_number)] = {
        'path': file_path,
        'type': media_type,
        'uploaded_by': str(update.effective_user.id),
        'timestamp': datetime.now().isoformat(),
        'size': os.path.getsize(file_path)
    }
    BotData.save(data)

    # Уведомляем сыновей
    sons_notified = 0
    for uid, user_data in data['users'].items():
        if user_data.get('role') == 'son' and user_data.get('current_lesson') == lesson_number:
            try:
                await context.bot.send_message(
                    chat_id=int(uid),
                    text=f"🎉 Урок #{lesson_number} готов!\n"
                         "Используйте кнопку '🎬 Получить урок', чтобы получить материалы.",
                    reply_markup=SON_KEYBOARD
                )
                sons_notified += 1
            except Exception as e:
                logger.error(f"Ошибка уведомления пользователя {uid}: {e}")

    await update.message.reply_text(
        f"✅ Урок #{lesson_number} успешно загружен!\n"
        f"Уведомлено {sons_notified} сыновей.",
        reply_markup=MOTHER_KEYBOARD
    )
    return ConversationHandler.END


async def get_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправка урока ученику"""
    data = BotData.load()
    user_id = str(update.effective_user.id)

    if data['users'].get(user_id, {}).get('role') != 'son':
        await update.message.reply_text("❌ Только сыновья могут получать уроки!", reply_markup=SON_KEYBOARD)
        return

    current_lesson = data['users'][user_id].get('current_lesson', 1)
    lesson = data['lessons'].get(str(current_lesson))
    if not lesson:
        keyboard = [[InlineKeyboardButton("📞 Уведомить маму", callback_data='notify_mother')]]
        await update.message.reply_text(
            f"❌ Урок #{current_lesson} еще не загружен!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    try:
        # Отправляем файл в зависимости от типа
        if lesson.get('type', 'video') == 'video':
            await update.message.reply_video(
                video=open(lesson['path'], 'rb'),
                caption=f"🎬 Урок #{current_lesson}",
                reply_markup=ReplyKeyboardRemove()
            )
        else:
            await update.message.reply_photo(
                photo=open(lesson['path'], 'rb'),
                caption=f"📸 Урок #{current_lesson}",
                reply_markup=ReplyKeyboardRemove()
            )

        # Обновляем текущий урок для ученика
        data['users'][user_id]['current_lesson'] = current_lesson + 1
        BotData.save(data)

        # Сохраняем номер урока для будущего отчета
        context.user_data['last_lesson'] = current_lesson

        keyboard = [[InlineKeyboardButton("📝 Сдать отчет", callback_data=f'submit_report_{current_lesson}')]]
        await update.message.reply_text(
            "✅ Урок успешно получен!\nПосле изучения сдайте отчет:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Ошибка отправки урока: {e}")
        await update.message.reply_text(
            "✅ Урок получен! Если возникли проблемы с просмотром, сообщите маме.",
            reply_markup=SON_KEYBOARD
        )


async def notify_mother(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Уведомление матери о необходимости загрузить урок"""
    query = update.callback_query
    await query.answer()

    data = BotData.load()
    user_id = str(query.from_user.id)
    user_data = data['users'].get(user_id, {})

    if user_data.get('role') != 'son':
        await query.edit_message_text(
            "❌ Только сыновья могут уведомлять маму!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="cancel")]])
        )
        return

    current_lesson = user_data.get('current_lesson', 1)
    son_name = user_data.get('name', 'Сын')
    mothers = [uid for uid, udata in data['users'].items() if udata.get('role') == 'mother']

    # Проверяем статус урока
    lesson_status = "еще не загружен"
    if str(current_lesson) in data['lessons']:
        lesson_status = "уже загружен"

    notification_sent = False
    for mother_id in mothers:
        try:
            await context.bot.send_message(
                chat_id=int(mother_id),
                text=f"👶 *{son_name}* ожидает урок #{current_lesson}\n"
                     f"Статус: _{lesson_status}_\n\n"
                     "Пожалуйста, загрузите его как можно скорее!",
                parse_mode='Markdown',
                reply_markup=MOTHER_KEYBOARD
            )
            notification_sent = True
        except Exception as e:
            logger.error(f"Ошибка уведомления матери {mother_id}: {e}")

    # Создаем новую клавиатуру для ответа сыну
    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Проверить доступность", callback_data="check_availability")]]
    )

    if notification_sent:
        await query.edit_message_text(
            f"📩 Уведомление отправлено матери!\n"
            f"Вы получите урок, как только он будет загружен.",
            reply_markup=reply_markup
        )
    else:
        await query.edit_message_text(
            "❌ Не удалось отправить уведомление матери",
            reply_markup=reply_markup
        )



async def remind_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Напоминание сыну о задании"""
    data = BotData.load()
    user_id = str(update.effective_user.id)

    if data['users'].get(user_id, {}).get('role') != 'mother':
        await update.message.reply_text("❌ Только матери могут напоминать о заданиях!", reply_markup=MOTHER_KEYBOARD)
        return

    # Находим всех сыновей
    sons = [(uid, udata) for uid, udata in data['users'].items() if udata.get('role') == 'son']
    if not sons:
        await update.message.reply_text("❌ Нет зарегистрированных сыновей!", reply_markup=MOTHER_KEYBOARD)
        return

    reminders_sent = 0
    for son_id, son_data in sons:
        current_lesson = son_data.get('current_lesson', 1)
        try:
            await context.bot.send_message(
                chat_id=int(son_id),
                text=f"🔔 Напоминание от мамы!\n"
                     f"Не забудь выполнить урок #{current_lesson}",
                reply_markup=SON_KEYBOARD
            )
            reminders_sent += 1
        except Exception as e:
            logger.error(f"Ошибка отправки напоминания {son_id}: {e}")

    await update.message.reply_text(
        f"📢 Напоминания отправлены {reminders_sent} сыновьям!",
        reply_markup=MOTHER_KEYBOARD
    )


async def list_lessons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список всех уроков"""
    data = BotData.load()
    user_id = str(update.effective_user.id)

    if data['users'].get(user_id, {}).get('role') != 'mother':
        await update.message.reply_text("❌ Только матери могут просматривать список уроков!",
                                        reply_markup=MOTHER_KEYBOARD)
        return

    if not data['lessons']:
        await update.message.reply_text("ℹ️ Пока нет ни одного урока.", reply_markup=MOTHER_KEYBOARD)
        return

    lessons_text = "📚 Список уроков:\n\n"
    for lesson_num, lesson_data in sorted(data['lessons'].items(), key=lambda x: int(x[0])):
        dt = datetime.fromisoformat(lesson_data['timestamp'])
        media_type = "🎬 Видео" if lesson_data.get('type') == 'video' else "📸 Фото"
        reports_count = len(data['reports'].get(lesson_num, []))

        lessons_text += (
            f"🔢 Урок #{lesson_num} ({media_type})\n"
            f"⏰ {dt.strftime('%d.%m.%Y %H:%M')}\n"
            f"📊 Отчетов: {reports_count}\n\n"
        )

    await update.message.reply_text(lessons_text, reply_markup=MOTHER_KEYBOARD)


async def request_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запрос отчета по уроку"""
    data = BotData.load()

    # Определяем, откуда пришел запрос (сообщение или callback)
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        user_id = str(query.from_user.id)
        message = query.message
    else:
        user_id = str(update.effective_user.id)
        message = update.message

    if data['users'].get(user_id, {}).get('role') != 'son':
        await message.reply_text("❌ Только сыновья могут сдавать отчеты!", reply_markup=SON_KEYBOARD)
        return ConversationHandler.END

    # Получаем последний пройденный урок
    last_lesson = context.user_data.get('last_lesson')
    if not last_lesson:
        current_lesson = data['users'][user_id].get('current_lesson', 1) - 1
        if current_lesson < 1:
            await message.reply_text("❌ У вас нет активных уроков для сдачи отчета", reply_markup=SON_KEYBOARD)
            return ConversationHandler.END
        context.user_data['report_lesson'] = current_lesson
    else:
        context.user_data['report_lesson'] = last_lesson

    lesson_number = context.user_data['report_lesson']

    await message.reply_text(
        f"📝 Отчет по уроку #{lesson_number}\n"
        "Введите комментарий к выполненному заданию:",
        reply_markup=ReplyKeyboardRemove()
    )
    return REPORT_TEXT


async def handle_report_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка текста отчета"""
    text = update.message.text
    lesson_number = context.user_data.get('report_lesson')

    if not lesson_number:
        await update.message.reply_text("❌ Ошибка: номер урока не найден", reply_markup=SON_KEYBOARD)
        return ConversationHandler.END

    context.user_data['report_text'] = text

    await update.message.reply_text(
        "📸 Теперь пришлите фото выполненного задания:",
        reply_markup=ReplyKeyboardRemove()
    )
    return REPORT_PHOTO


async def handle_report_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка фото отчета"""
    lesson_number = context.user_data.get('report_lesson')
    text = context.user_data.get('report_text')
    user_id = str(update.effective_user.id)

    if not lesson_number or not text:
        await update.message.reply_text("❌ Ошибка: данные отчета неполные", reply_markup=SON_KEYBOARD)
        return ConversationHandler.END

    # Сохраняем фото отчета
    report_dir = os.path.join(REPORTS_DIR, str(lesson_number))
    os.makedirs(report_dir, exist_ok=True)

    photo = update.message.photo[-1]
    file_path = os.path.join(report_dir, f"{user_id}.jpg")
    await (await photo.get_file()).download_to_drive(file_path)

    await save_report(context, user_id, lesson_number, text, file_path, update.effective_user.full_name)

    await update.message.reply_text(
        "✅ Отчет отправлен на проверку!",
        reply_markup=SON_KEYBOARD
    )
    return ConversationHandler.END


async def save_report(context: ContextTypes.DEFAULT_TYPE, user_id: str, lesson_number: int,
                      text: str, photo_path: str, user_name: str):
    """Сохраняет отчет и уведомляет мать"""
    data = BotData.load()

    # Сохраняем отчет
    if str(lesson_number) not in data['reports']:
        data['reports'][str(lesson_number)] = []

    report = {
        'user_id': user_id,
        'text': text,
        'timestamp': datetime.now().isoformat(),
        'status': 'pending'
    }

    if photo_path:
        report['photo'] = photo_path

    data['reports'][str(lesson_number)].append(report)
    report_idx = len(data['reports'][str(lesson_number)]) - 1
    BotData.save(data)

    # Уведомляем маму
    mothers = [uid for uid, udata in data['users'].items() if udata.get('role') == 'mother']
    for mother_id in mothers:
        try:
            message_text = (
                f"📝 Получен отчет по заданию #{lesson_number}!\n"
                f"👤 От: {user_name}\n"
                f"📄 Комментарий: {text}"
            )

            keyboard = [
                [
                    InlineKeyboardButton("✅ Принять", callback_data=f"approve_{lesson_number}_{user_id}_{report_idx}"),
                    InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{lesson_number}_{user_id}_{report_idx}")
                ]
            ]

            if photo_path:
                await context.bot.send_photo(
                    chat_id=int(mother_id),
                    photo=open(photo_path, 'rb'),
                    caption=message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await context.bot.send_message(
                    chat_id=int(mother_id),
                    text=message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        except Exception as e:
            logger.error(f"Ошибка отправки отчета матери {mother_id}: {e}")


async def handle_report_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка решения по отчету"""
    query = update.callback_query
    await query.answer()

    action, lesson_number, user_id, report_idx = query.data.split('_')
    lesson_number = int(lesson_number)
    report_idx = int(report_idx)

    data = BotData.load()

    # Обновляем статус отчета
    if str(lesson_number) not in data['reports'] or report_idx >= len(data['reports'][str(lesson_number)]):
        await query.answer("❌ Ошибка: отчет не найден", show_alert=True)
        return

    report = data['reports'][str(lesson_number)][report_idx]
    if action == 'approve':
        report['status'] = 'approved'
        status_text = "✅ принят"
        son_message = f"🎉 Мама приняла твой отчет по уроку #{lesson_number}!"
    else:
        report['status'] = 'rejected'
        status_text = "❌ отклонен"
        son_message = f"😢 Мама отклонила твой отчет по уроку #{lesson_number}.\nПожалуйста, переделай задание и отправь отчет заново."

    BotData.save(data)

    # Уведомляем сына
    try:
        await context.bot.send_message(
            chat_id=int(user_id),
            text=son_message,
            reply_markup=SON_KEYBOARD
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления пользователя {user_id}: {e}")

    # Обновляем сообщение с отчетом
    try:
        if query.message.photo:
            await query.edit_message_caption(
                caption=f"{query.message.caption}\n\nСтатус: {status_text}"
            )
        else:
            await query.edit_message_text(
                text=f"{query.message.text}\n\nСтатус: {status_text}"
            )
    except Exception as e:
        logger.error(f"Ошибка обновления сообщения: {e}")


async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена действия"""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        user_id = str(query.from_user.id)
        message = query.message
    else:
        user_id = str(update.effective_user.id)
        message = update.message

    data = BotData.load()
    role = data['users'].get(user_id, {}).get('role')

    if role == 'mother':
        reply_markup = MOTHER_KEYBOARD
    else:
        reply_markup = SON_KEYBOARD

    if update.callback_query:
        await query.edit_message_text("❌ Действие отменено")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Возврат в главное меню",
            reply_markup=reply_markup
        )
    else:
        await message.reply_text("❌ Действие отменено", reply_markup=reply_markup)
    return ConversationHandler.END


async def check_availability(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка доступности урока"""
    query = update.callback_query
    await query.answer()

    data = BotData.load()
    user_id = str(query.from_user.id)

    if data['users'].get(user_id, {}).get('role') != 'son':
        await query.edit_message_text("❌ Только сыновья могут проверять уроки!", reply_markup=SON_KEYBOARD)
        return

    current_lesson = data['users'][user_id].get('current_lesson', 1)
    await show_son_status(query.message, data, user_id)


def main() -> None:
    """Запуск бота"""
    # Создаем папки если их нет
    for folder in [LESSONS_DIR, REPORTS_DIR]:
        os.makedirs(folder, exist_ok=True)

    application = Application.builder().token("7636649473:AAGKLzuI-az8HNnuZamhUgLYDMrhfvDJmY0").build()

    # Обработчики команд и сообщений
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            MessageHandler(filters.Regex('^📝 Создать урок$'), request_lesson),
            MessageHandler(filters.Regex('^🎬 Получить урок$'), get_lesson),
            MessageHandler(filters.Regex('^📝 Сдать отчет$'), request_report),
            CallbackQueryHandler(request_report, pattern='^submit_report_')
        ],
        states={
            ROLE_SELECTION: [CallbackQueryHandler(role_selection, pattern='^(mother|son)$')],
            UPLOAD_NEXT_LESSON: [MessageHandler(filters.VIDEO | filters.PHOTO, handle_lesson_media)],
            REPORT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_report_text)],
            REPORT_PHOTO: [MessageHandler(filters.PHOTO, handle_report_photo)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_action),
            MessageHandler(filters.Regex('^Отмена$'), cancel_action),
            CallbackQueryHandler(cancel_action, pattern='^cancel_report$')
        ],
        per_message=False
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('reset_data', BotData.reset))

    # Обработчики кнопок
    application.add_handler(MessageHandler(filters.Regex('^📋 Список уроков$'), list_lessons))
    application.add_handler(MessageHandler(filters.Regex('^🔔 Напомнить о задании$'), remind_task))

    # Обработчики callback-кнопок
    application.add_handler(CallbackQueryHandler(notify_mother, pattern='^notify_mother$'))
    application.add_handler(CallbackQueryHandler(check_availability, pattern='^check_availability$'))
    application.add_handler(CallbackQueryHandler(handle_report_review, pattern='^(approve|reject)_\d+_\d+_\d+$'))

    application.run_polling()
    logger.info("Бот запущен")


if __name__ == '__main__':
    main()