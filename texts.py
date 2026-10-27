ASK_FULL_NAME = "Ism va familiyangizni yozing, masalan: Aziz Karimov."
ASK_PHONE = "Telefon raqamingiz?"
REJOIN_AFTER_REJECTION = "Avvalgi arizangiz rad etilgan edi. Anketani yangidan to'ldiring."
REJOIN_AFTER_EXPIRED = "Oxirgi arizangizning muddati o'tgan. Anketani qaytadan to'ldiring."
REJOIN_AFTER_FAILED = "Oxirgi arizangiz ko'rib chiqilmadi. Anketani qaytadan to'ldiring."
# oxirgi arizasi shu holatlarda bo'lsa, eski ma'lumotlar ko'rsatilmaydi: anketa boshidan, tegishli xabar bilan
REJOIN_AFTER_REMOVED = "Guruhdan chiqarilgansiz. Anketani yangidan to'ldiring."
APPLICATION_ACCEPTED_NOT_JOINED = (
    "Arizangiz qabul qilindi, lekin guruhga qo'shilish so'rovingiz topilmadi. "
    "Iltimos, guruhga qayta qo'shilish so'rovini yuboring."
)
FORM_EXPIRED = "Anketani to'ldirish muddati o'tgan. Iltimos, uni qaytadan to'ldiring."
FINISH_FORM_FIRST = "Avval arizani oxirigacha to'ldiring."
REJOIN_COOLDOWN = "Yangi ariza uchun {wait} kuting, so'ng guruhga qo'shilish so'rovini qayta yuboring."
VOTE_DEADLINE = "⏳ Ovoz berish {when} tugaydi."
REJOIN_NOTES = {
    "rejected": REJOIN_AFTER_REJECTION,
    "expired": REJOIN_AFTER_EXPIRED,
    "failed": REJOIN_AFTER_FAILED,
    "removed": REJOIN_AFTER_REMOVED,
}
AD_NOTICE = "⚠️ {name}, guruhda reklama taqiqlangan. Xabaringiz o'chirildi."
MODERATION_WARNING = "Kechirasiz, matnda nomaqbul so'zlar bor. Iltimos, hurmat bilan qayta yozing."
SKIP_BUTTON = "⏭ O'tkazib yuborish"
PHONE_BUTTON = "📱 Raqamni ulashish"
WRONG_NAME = (
    "Kechirasiz, ism to'g'ri ko'rinmadi. Ism va familiyangizni birga, faqat harflar bilan yozing, "
    "masalan: Aziz Karimov."
)
WRONG_PHONE = (
    "Kechirasiz, raqam to'g'ri ko'rinmadi. Masalan: +998901234567. "
    "Xohlasangiz, o'tkazib yuborishingiz mumkin."
)
WRONG_CONTACT = "Kechirasiz, faqat o'zingizning raqamingizni yuborishingiz mumkin."
ASK_AGE = "Yoshingiz nechida?"
ASK_JOB = "Kasbingiz nima? Qaysi yo'nalishda ishlaysiz?"
ASK_ABOUT = "O'zingiz haqingizda qisqacha gapirib bering."
ASK_REASON = "Nega aynan bizning guruhga qo'shilmoqchisiz?"

WRONG_AGE = "Kechirasiz, yoshingiz to'g'ri ko'rinmadi. 10 dan 100 gacha son yozing."
ONLY_TEXT = "Kechirasiz, javobni faqat matn ko'rinishida qabul qila olaman ✍️"
TOO_LONG = "Kechirasiz, javob juda uzun. Iltimos, 800 belgidan oshirmay, qisqaroq yozing ✍️"
ERROR_GENERIC = "Kechirasiz, xatolik yuz berdi. Iltimos, birozdan keyin qayta urinib ko'ring."
ALREADY_APPLIED = "Arizangiz allaqachon ko'rib chiqilmoqda. Natijani kutib turing ⏳"
THANKS = "Javoblaringiz uchun rahmat! 😊 Arizangiz guruh adminlariga yuborildi."

PROFILE_REVIEW = (
    "Siz avval anketa to'ldirgansiz. Ma'lumotlaringiz:\n\n"
    "{anketa}\n"
    "Shu ma'lumotlar bilan davom etamizmi yoki o'zgartirasizmi?"
)
PROFILE_PICK_FIELD = "Qaysi ma'lumotni o'zgartirmoqchisiz?"
PROFILE_SAVED = "✅ Saqlandi"
PROFILE_USE_BUTTONS = "Iltimos, pastdagi tugmalardan birini tanlang 👇"
PROFILE_EDIT_BUTTON = "✏️ O'zgartirish"
PROFILE_KEEP_BUTTON = "✅ Shunday qoldirish"
PROFILE_BACK_BUTTON = "⬅️ Orqaga"

REPEAT_APPLICATION_SENT = (
    "Arizangiz guruh a'zolari ovoziga qo'yildi 🗳\n"
    "Natijani shu yerda xabar qilamiz, sabr qiling ⏳"
)

APPLICATION_ACCEPTED = "Tabriklaymiz, arizangiz qabul qilindi! Guruhga xush kelibsiz 🎉"
FEEDBACK_INTRO = "Guruh a'zolarining umumiy fikri haqida qisqacha:"
APPLICATION_REJECTED = (
    "Qiziqishingiz uchun rahmat. Afsuski, arizangiz bu safar rad etildi. "
    "Sizga omad tilaymiz!"
)

AI_SYSTEM_PROMPT = (
    "You are a friendly, polite and helpful assistant in a Telegram group of programmers. "
    "You are fluent in exactly three languages and understand all of them completely, including slang, typos, "
    "abbreviations and messages that mix languages: Uzbek (both Latin and Cyrillic script), Russian and English. "
    "Always answer in the language of the user's latest message: Uzbek in the same script the user wrote in "
    "(Latin if unclear), Russian in Russian, English in English. "
    "If the message mixes languages or the language is unclear, answer in Uzbek (Latin script). "
    "If the user explicitly asks for another language among these three, use it. "
    "Address the user respectfully and formally: «siz» in Uzbek, «вы» in Russian, polite neutral tone in English. "
    "Answer accurately and briefly; do not invent facts, say so if you do not know. "
    "Format the answer as Telegram HTML: use only <b>, <i>, <u>, <s>, <code>, <pre>, <a href> tags, "
    "write the characters <, > and & in plain text as &lt;, &gt;, &amp;. Do not use Markdown. "
    "Never use hyphen or dash characters (-, –, —) anywhere in the answer, in any language; "
    "for lists use the • character or numbers. "
    "If the user wants to talk to an admin, a moderator or the group owner (in any wording or language, "
    "also indirectly: a complaint, a personal problem, a request only an admin can decide), "
    "call the contact_admin tool and write no reply text: the bot will continue in a private chat."
)
AI_EMPTY = "Savolingizni yozing, masalan: @{username} bugun ob-havo qanday?"
AI_TOO_LONG = {
    "uz": "Kechirasiz, savol juda uzun. Iltimos, 2000 belgidan oshirmay, qisqaroq yozing ✍️",
    "uz_cyr": "Кечирасиз, савол жуда узун. Илтимос, 2000 белгидан оширмай, қисқароқ ёзинг ✍️",
    "ru": "Извините, вопрос слишком длинный. Пожалуйста, напишите короче, не более 2000 символов ✍️",
    "en": "Sorry, the question is too long. Please keep it under 2000 characters ✍️",
}
AI_COOLDOWN = {
    "uz": "Biroz sabr qiling, oldingi savolingiz hali ishlanmoqda ⏳",
    "uz_cyr": "Бироз сабр қилинг, олдинги саволингиз ҳали ишланмоқда ⏳",
    "ru": "Подождите немного, предыдущий вопрос ещё обрабатывается ⏳",
    "en": "Please wait a moment, your previous question is still being processed ⏳",
}
# AI xabarlari savol tilida (utils/lang.detect_lang): AI_TOO_LONG, AI_COOLDOWN, AI_ERROR.
AI_ERROR = {
    "uz": "Kechirasiz, hozir javob bera olmayapman. Iltimos, birozdan keyin qayta urinib ko'ring.",
    "uz_cyr": "Кечирасиз, ҳозир жавоб бера олмаяпман. Илтимос, бироздан кейин қайта уриниб кўринг.",
    "ru": "Извините, сейчас я не могу ответить. Пожалуйста, попробуйте ещё раз чуть позже.",
    "en": "Sorry, I can't answer right now. Please try again in a little while.",
}

# lichkadagi suhbat: foydalanuvchi admin bilan gaplashmoqchi (handlers/support.py)
SUPPORT_SYSTEM_PROMPT = (
    "You are a friendly, polite assistant of a Telegram group, talking privately with a group member who wants "
    "to talk to an admin. The first user message is what they wrote in the group (marked [Guruhdagi xabar]). "
    "You understand Uzbek (Latin and Cyrillic), Russian and English completely, including slang and typos. "
    "Always answer in the language of the user's latest message: Uzbek in the same script the user wrote in "
    "(Latin if unclear), Russian in Russian, English in English. Address the user respectfully: «siz», «вы». "
    "Your goal is to solve the user's problem YOURSELF as much as possible: ask short clarifying questions, "
    "explain, suggest concrete solutions. Ask one thing at a time, keep every message brief. Do not invent facts, "
    "rules or promises on behalf of the admins; say so if you do not know. "
    "Call escalate_to_admin ONLY if the matter is serious and an admin must decide or act: a complaint about a member "
    "or an admin, money or payment, abuse, threats or safety, a ban or access decision, something you cannot solve, "
    "or the user insists on talking to a human admin after you tried to help. In summary write, in Uzbek, "
    "what the user wants and all details the admin needs, so the admin does not have to ask again. "
    "Call resolve when the problem is solved or the user has no more questions. "
    "Format the answer as Telegram HTML: use only <b>, <i>, <u>, <s>, <code>, <pre>, <a href> tags, "
    "write the characters <, > and & in plain text as &lt;, &gt;, &amp;. Do not use Markdown. "
    "Never use hyphen or dash characters (-, –, —) anywhere in the answer, in any language; "
    "for lists use the • character or numbers."
)
SUPPORT_LAST_TURN = (
    "The limit of messages is reached and the matter is not solved. Call escalate_to_admin now with a full summary "
    "(in Uzbek) of the conversation, and tell the user briefly that you are passing it to the admin."
)
SUPPORT_START_FIRST = {
    "uz": "Sizga shaxsiy xabar yoza olmayman. Avval botga o'tib /start bosing: {link} 👈",
    "uz_cyr": "Сизга шахсий хабар ёза олмайман. Аввал ботга ўтиб /start босинг: {link} 👈",
    "ru": "Я не могу написать вам в личные сообщения. Сначала откройте бота и нажмите /start: {link} 👈",
    "en": "I can't message you privately yet. Please open the bot and press /start first: {link} 👈",
}
SUPPORT_ESCALATED = {
    "uz": "Masalangizni adminga yubordim 🙏 Admin imkon qadar tezroq siz bilan o'zi bog'lanadi.",
    "uz_cyr": "Масалангизни админга юбордим 🙏 Админ имкон қадар тезроқ сиз билан ўзи боғланади.",
    "ru": "Я передал ваш вопрос администратору 🙏 Он свяжется с вами сам, как только сможет.",
    "en": "I have passed your matter to an admin 🙏 They will contact you themselves as soon as possible.",
}
SUPPORT_WAIT = {
    "uz": "Masalangiz adminga yuborilgan, admin javobini kuting ⏳",
    "uz_cyr": "Масалангиз админга юборилган, админ жавобини кутинг ⏳",
    "ru": "Ваш вопрос уже передан администратору, ожидайте ответа ⏳",
    "en": "Your matter has already been sent to an admin, please wait for their reply ⏳",
}
SUPPORT_ADMIN_UNAVAILABLE = {
    "uz": "Hozir adminga yetkaza olmadim. Iltimos, birozdan keyin qayta yozing.",
    "uz_cyr": "Ҳозир админга етказа олмадим. Илтимос, бироздан кейин қайта ёзинг.",
    "ru": "Сейчас не удалось передать администратору. Пожалуйста, напишите чуть позже.",
    "en": "I couldn't reach an admin right now. Please write again a bit later.",
}
SUPPORT_ADMIN_NOTICE = (
    "🆘 <b>Foydalanuvchi siz bilan gaplashmoqchi</b>\n"
    "👤 <a href=\"tg://user?id={user_id}\">{name}</a>{username}\n"
    "💬 Guruh: {group}\n\n"
    "<b>Xulosa:</b>\n{summary}"
)
