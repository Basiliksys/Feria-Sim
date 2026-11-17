# -*- coding: utf-8 -*-
"""Довідкові дані світу Ферії, яких немає у .map-файлі.

Усе, що тут описано, — «допис» до карти: календар, пори року, категорії попиту,
валюти, усі держави з Obsidian-сховища, гільдії, найманці, ордени, башти магів,
тип правителів, таблиці подій та сценарій Четвертого Походу на Кірос.
"""

# ----------------------------------------------------------------------------
# Календар
# ----------------------------------------------------------------------------
ERA_SHORT = "Н.Е."
START_YEAR = 1250          # поточний рік: 1250 Н.Е. (= 3250 Е.С. у хронології Ферії)
MAP_YEAR = 3060            # рік у .map файлі Ферії (Azgaar)
MAP_YEAR_OFFSET = START_YEAR - MAP_YEAR  # зсув історичних подій з карти

MONTHS_UK = [
    "Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень",
    "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень",
]

# Географічний поділ континентів за назвами ландмас з .map
KIROS_LANDMASSES = {
    "Zugrimfanu", "Linnerg", "Maveham", "Wiskirk", "Witford", "Sacium", "Diguca", "Draconic",
}

# ----------------------------------------------------------------------------
# Попит
# ----------------------------------------------------------------------------
CATEGORIES = ["food", "utilities", "construction", "luxury", "military"]
CATEGORY_UK = {
    "food": "Їжа", "utilities": "Побут і паливо", "construction": "Будівництво",
    "luxury": "Розкіш", "military": "Військове постачання",
}
CAL_TARGET = {"food": 1.06, "utilities": 1.0, "construction": 0.9, "luxury": 0.9}
URBAN_LUXURY_BOOST = 2.5
URBAN_CONSTR_BOOST = 1.8

# ----------------------------------------------------------------------------
# Гроші: 1 одиниця вартості в .map (зерно = 1) = ``VALUE_TO_MM`` мідяків.
# ----------------------------------------------------------------------------
VALUE_TO_MM = 10000        # 1 од. = 1 зм (курс сховища 1 зм = 100 см = 10 000 мм)
COIN_NAMES = [("пм", 1_000_000), ("зм", 10_000), ("см", 100), ("мм", 1)]


def fmt_coins(value_units: float) -> str:
    """Переводить одиниці вартості у монети сховища (пм/зм/см/мм)."""
    mm = int(round(value_units * VALUE_TO_MM))
    if mm <= 0:
        return "0 мм"
    parts = []
    for name, size in COIN_NAMES:
        q, mm = divmod(mm, size)
        if q:
            parts.append(f"{q} {name}")
    return " ".join(parts[:2])


# ----------------------------------------------------------------------------
# Українські назви товарів
# ----------------------------------------------------------------------------
GOODS_UK = {
    1: "Деревина", 2: "Камінь", 3: "Мармур", 4: "Залізо", 5: "Мідь", 6: "Олово",
    7: "Срібло", 8: "Золото", 9: "Зерно", 10: "Худоба", 11: "Риба", 12: "Дичина",
    13: "Вино", 14: "Оливки", 15: "Мед", 16: "Сіль", 17: "Фініки", 18: "Коні",
    19: "Слони", 20: "Верблюди", 21: "Коноплі", 22: "Перлини", 23: "Самоцвіти",
    24: "Фарби", 25: "Ладан", 26: "Шовк", 27: "Прянощі", 28: "Бурштин",
    29: "Хутра", 30: "Вівці", 31: "Раби", 32: "Смола", 33: "Селітра",
    34: "Вугілля", 35: "Олія", 36: "Червоне дерево", 37: "Кити/ворвань",
    38: "Цукрова тростина", 39: "Чай", 40: "Тютюн", 41: "Глина", 42: "Білий пісок",
    43: "Шкіра", 44: "Сукно", 45: "Одяг", 46: "Кераміка", 47: "Скло",
    48: "Канати", 49: "Папір", 50: "Чорнило", 51: "Книги", 52: "Вітрила",
    53: "Кораблі", 54: "Взуття", 55: "Збруя", 56: "Бочки", 57: "Бронза",
    58: "Інструменти", 59: "Зброя", 60: "Порох", 61: "Артилерія", 62: "Монети",
    63: "Коштовності", 64: "Консерви", 65: "Оцет", 66: "Сир", 67: "Пиво",
    68: "Лікер", 69: "Свічки", 70: "Мило", 71: "Парфуми",
}

BULKY_TAGS = {"construction": 0.9, "fuel": 1.0, "food": 1.0, "ore": 1.1,
              "luxury": 0.25, "currency": 0.1}


def good_uk(gid, goods_dict=None):
    """Повертає українську назву товару з безпечним фолбеком для нестандартних ID."""
    if gid in GOODS_UK:
        return GOODS_UK[gid]
    if goods_dict and gid in goods_dict:
        return translit(goods_dict[gid].get("name", f"Товар #{gid}"))
    return f"Товар #{gid}"

# ----------------------------------------------------------------------------
# Відомі держави зі сховища (ключ — назва на карті)
# ----------------------------------------------------------------------------
KNOWN_STATES = {
    # ===================== КОНТИНЕНТ ТУРС =====================
    "Nimanchia": dict(
        uk="Імперія Німан", cont="Турс", capital="Несплой", coins="Золотий Сенатор",
        gov="Станово-олігархічна імперія (Залізний Сенат)",
        ruler=("Імператор Анрі IV де Несплой", "male"),
        traits=["industrial", "warlike", "technocratic"],
        note="Індустріальний та військовий колос Турсу під фактичним контролем Залізного Сенату; проєкт «Егіда Безсмертя».",
    ),
    "Ondia": dict(
        uk="Імперія Ондія", cont="Турс", capital="Буранвіль", coins="Золотий Грифон",
        gov="Феодальна станова імперія лицарського права",
        ruler=("Імператор Леон II де Буранвіль", "male"),
        traits=["pious", "feudal", "martial"],
        note="Лицарські династії, союз із магами Білих Ряс та Орденом Срібного Грифона.",
    ),
    "Lial": dict(
        uk="Ліяльська Імперія", cont="Турс", capital="Разіка", coins="Золотий Динар",
        gov="Східна кочова деспотія / Шаханат",
        ruler=("Емір Бахтіяр", "male"),
        traits=["mercantile", "desert", "cautious"],
        note="Пустельна імперія кланів рахнідів; караванна монополія через Великі Дюни.",
    ),
    "Nagen": dict(
        uk="Республіка Наген", cont="Турс", capital="Міт'джесс", coins="Золота Крона",
        gov="Торговельно-олігархічна морська республіка (Рада Капітанів)",
        ruler=("Рада Капітанів", "collective"),
        traits=["naval", "mercantile", "whaling"],
        note="Китобійний промисел, полярні торгові синдикати, алхімічний реліктовий лід і хутра.",
    ),
    "Athas": dict(
        uk="Республіка Атас", cont="Турс", capital="Нар'тунек", coins="Срібний Атасів",
        gov="Плутократична торгова республіка",
        ruler=("Рада Директорів «Артасу»", "collective"),
        traits=["mercantile", "smuggling"],
        note="Фінансове серце Ферії, суверенна база міжнародної гільдії «Артас» і прикордонних караванів Макаша.",
    ),
    "Lando": dict(
        uk="Королівство Ландо", cont="Турс", capital="Інтафон", coins="Ландійський Лев",
        gov="Феодально-кланова монархія 35 Земель",
        ruler=("Верховний Король Кеннет III Мак-Інтафон", "male"),
        traits=["warlike", "feudal"],
        note="Найбільше королівство сходу Турсу; могутні військові клани та друїди.",
    ),
    "Donia": dict(
        uk="Донійська Теократія", cont="Турс", capital="Мартемп'єр", coins="Світлий Дукат",
        gov="Папська / Архієпископська теократія",
        ruler=("Верховний Ієрарх Донії", "male"),
        traits=["pious", "inquisitorial"],
        note="Хранителька релігійної чистоти перешийка Турсу; Лицарі Священного Променя.",
    ),
    "Nisar": dict(
        uk="Теократія Нісар", cont="Турс", capital="Ррокказ'лу", coins="Зоряна Монета",
        gov="Жрецька теократія",
        ruler=("Верховний Пророк Зорі", "male"),
        traits=["pious", "cautious"],
        note="Священні землі народів півночі та сходу Турсу; Орден Пророків Зорі.",
    ),
    "Szez": dict(
        uk="Сезанська Імперія", cont="Турс", capital="Хітовар", coins="Залізний Динар",
        gov="Жорстка військова диктатура",
        ruler=("Верховний Командор Сезану", "male"),
        traits=["warlike", "tyrant"],
        note="Мілітаризований суперник Ліялю зі спадковим військовим станом і облоговою справою.",
    ),
    "Mos": dict(
        uk="Королівство Мос", cont="Турс", capital="Мар'ті", coins="Срібний Півмісяць",
        gov="Приморський султанат Внутрішнього Затоку",
        ruler=("Султан Мар'ті", "male"),
        traits=["naval", "mercantile"],
        note="Багатий торговий султанат на берегах внутрішньої затоки Турсу.",
    ),
    "Charenia": dict(
        uk="Королівство Чаренія", cont="Турс", capital="Міньї", coins="Срібна Лілея",
        gov="Феодальне королівство",
        ruler=None, traits=["feudal", "cautious"],
        note="Стародавнє луаріанське королівство центрального Турсу.",
    ),
    "Satia": dict(
        uk="Князівство Сатія", cont="Турс", capital="Мордес", coins="Срібна Лілея",
        gov="Витончене феодальне князівство",
        ruler=None, traits=["mercantile", "reformer"],
        note="Придворна дипломатія, виноробство й ремесла східної долини.",
    ),
    "Boisia": dict(
        uk="Князівство Бойсія", cont="Турс", capital="Мале", coins="Срібна Лілея",
        gov="Спадкове лицарське князівство",
        ruler=None, traits=["martial", "feudal"],
        note="Лицарське князівство на перехресті західного Турсу.",
    ),
    "Foria": dict(
        uk="Князівство Форія", cont="Турс", capital="Баконжен", coins="Срібна Лілея",
        gov="Буферне феодальне князівство",
        ruler=None, traits=["smuggling", "cautious"],
        note="Буфер між Ондією та Ліалем; земля контрабандистів і перевалочних баз.",
    ),
    "Bareaux": dict(
        uk="Королівство Барео", cont="Турс", capital="Барео", coins="Залізна Марка",
        gov="Феодальне королівство гірських перевалів",
        ruler=None, traits=["martial", "industrial"],
        note="Суворі південні гори, гарнізонні фортеці й залізні шахти.",
    ),
    "Rogentia": dict(
        uk="Королівство Рогентія", cont="Турс", capital="Рувре", coins="Золотий Якір",
        gov="Приморське королівство",
        ruler=None, traits=["naval", "mercantile"],
        note="Потужні верфі та розвинений торговельний флот на південному заході Турсу.",
    ),
    "Vitrates": dict(
        uk="Королівство Вітрейтс", cont="Турс", capital="Вітрейтс", coins="Срібний Соверен",
        gov="Острівне королівство проток",
        ruler=None, traits=["naval", "warlike"],
        note="Володар островів і проток у центральній затоці Турсу.",
    ),
    "Condia": dict(
        uk="Протекторат Кондія", cont="Турс", capital="Адфлуенсіум", coins="Роміанський Денарій",
        gov="Роміанський протекторат",
        ruler=None, traits=["feudal", "martial"],
        note="Західний роміанський анклав Турсу.",
    ),
    "Coria": dict(
        uk="Герцогство Корія", cont="Турс", capital="Августако", coins="Роміанський Денарій",
        gov="Роміанське герцогство",
        ruler=None, traits=["cautious", "pious"],
        note="Спадкоємець давніх роміанських традицій на узбережжі.",
    ),
    "Caj": dict(
        uk="Протекторат Кай", cont="Турс", capital="Шейз", coins="Караванний Драхм",
        gov="Степовий протекторат",
        ruler=None, traits=["desert", "cautious"],
        note="Прикордоння між степами Адж'Снага та землями Рахнід.",
    ),
    "Cek'su": dict(
        uk="Князівство Сек'су", cont="Турс", capital="Сек'су", coins="Срібний Драхм",
        gov="Східне прикордонне князівство",
        ruler=None, traits=["warlike", "desert"],
        note="Прикордонні степи східного Турсу.",
    ),
    "Nar't": dict(uk="Велике герцогство Нар'т", cont="Турс", capital="Крусугеф", coins="Срібний Грош",
                  gov="Степове герцогство", ruler=None, traits=["warlike"], note="Північно-східний степ Турсу."),
    "Ra": dict(uk="Герцогство Ра", cont="Турс", capital="Грессе", coins="Срібний Грош",
               gov="Степове герцогство", ruler=None, traits=["desert"], note="Між Нагеном, Нісаром та Атасом."),
    "Neu": dict(uk="Протекторат Ной", cont="Турс", capital="Толінессон", coins="Золотий Сенатор",
                gov="Протекторат на межі Німану", ruler=None, traits=["cautious"], note="Буферний протекторат на схід від Німану."),
    "Autia": dict(uk="Гептархія Аутія", cont="Турс", capital="Аргіс", coins="Срібна Лілея",
                  gov="Союз семи міст", ruler=None, traits=["mercantile"], note="Південно-західний союз міст Турсу."),
    "Ereia": dict(uk="Ерейська Марка", cont="Турс", capital="Брідівґдура", coins="Срібна Лілея",
                  gov="Прикордонна марка", ruler=None, traits=["martial"], note="Прикордоння біля Ландо."),

    # ===================== КОНТИНЕНТ КІРОС =====================
    "Galg": dict(
        uk="Імперія Галган", cont="Кірос", capital="Нугукзінб", coins="Адамантовий Таллер",
        gov="Західна адамантова техно-імперія трьох каст",
        ruler=("Рада Трьох Кілець", "collective"),
        traits=["industrial", "besieged", "technocratic"],
        note="Спадкоємиця Калфонду; підземні форти-гіпогеї, 3000 парових колосів-големів; бореться з прокляттям «Чорної Іржі».",
    ),
    "Burt": dict(
        uk="Республіка Берт", cont="Кірос", capital="Грімтіба", coins="Вагове срібло",
        gov="Воєнна республіка доппельзольднерів",
        ruler=("Рада Берту", "collective"),
        traits=["warlike", "besieged", "industrial"],
        note="Земля фламберга й залізної індустрії; кругова оборона Східного Молота проти орд нежиті.",
    ),
    "Sulkun": dict(
        uk="Королівство Сулкун", cont="Кірос", capital="Сулкун", coins="Сулкунський Залізний Грош",
        gov="Священне королівство-бастіон",
        ruler=("Рада Реєстрових Полків", "collective"),
        traits=["besieged", "warlike", "pious"],
        note="Священна твердиня Північного Сакрального Валу; оборону тримають Реєстрові полки.",
    ),
    "Olds": dict(
        uk="Королівство Олдс", cont="Кірос", capital="Стігкан", coins="Рунний Срібник",
        gov="Традиційна патріархальна монархія",
        ruler=None, traits=["warlike", "besieged"],
        note="Найдавніша монархія Північного Валу; царство рунного льоду, воює проти Берта.",
    ),
    "Usharb": dict(
        uk="Королівство Ушарб", cont="Кірос", capital="Інгарт", coins="Вагове срібло",
        gov="Військова монархія",
        ruler=None, traits=["martial", "besieged"],
        note="Вірний союзник Берта; гранітні фортеці та важкі облогові гармати на алхімічній суміші.",
    ),
    "Nuhal": dict(
        uk="Об'єднане Королівство Нухал", cont="Кірос", capital="Дізір", coins="Фіордний Срібник",
        gov="Союзна монархія фіордів",
        ruler=None, traits=["naval", "besieged"],
        note="Північно-східний бастіон Сакрального Валу.",
    ),
    "Morn": dict(
        uk="Королівство Морн", cont="Кірос", capital="Барік", coins="Вагове срібло",
        gov="Феодальне королівство",
        ruler=None, traits=["feudal", "besieged"],
        note="Феодальне королівство Північного Валу, васальні зв'язки з Бертом.",
    ),
    "Nulfod": dict(
        uk="Королівство Нулфод", cont="Кірос", capital="Хабігі", coins="Вагове срібло",
        gov="Східноприбережне королівство",
        ruler=None, traits=["martial", "besieged"],
        note="Тримає оборону вздовж східного узбережжя Кіросу.",
    ),
    "Sad": dict(
        uk="Королівство Сад", cont="Кірос", capital="Нартек", coins="Вагове срібло",
        gov="Східне королівство-форпост",
        ruler=None, traits=["cautious", "besieged"],
        note="Південно-східний сусід Нулфоду та Берта.",
    ),
    "Skip": dict(
        uk="Королівство Скіп", cont="Кірос", capital="Скіптон", coins="Хрестовий Срібник",
        gov="Лицарське королівство",
        ruler=None, traits=["martial", "pious", "besieged"],
        note="Опора важкої лицарської кінноти на південному заході Кіросу; випалює гнізда нежиті.",
    ),
    "Soroughia": dict(
        uk="Королівство Сороугія", cont="Кірос", capital="Хелсхед", coins="Вагове срібло",
        gov="Південно-західне королівство боліт",
        ruler=None, traits=["besieged", "cautious"],
        note="Болотяні укріплення південного заходу Кіросу.",
    ),
    "Sho": dict(
        uk="Велике герцогство Шо", cont="Кірос", capital="Мурі", coins="Вагове срібло",
        gov="Велике герцогство",
        ruler=None, traits=["feudal", "besieged"],
        note="Південний союзник Сороугії.",
    ),
    "Totlia": dict(
        uk="Князівство Тотлія", cont="Кірос", capital="Шарботес", coins="Вагове срібло",
        gov="Князівство східного фронту",
        ruler=("Король Ніт Хелсбіа", "male"),
        traits=["warlike", "besieged"],
        note="Форпост східного фронту (мер Реджиналь Шарботес); приймає перші удари проривів немертвих.",
    ),
    "Cleore": dict(
        uk="Велике герцогство Клеор", cont="Кірос", capital="Берлінгем", coins="Сонячний Срібник",
        gov="Твердиня лицарів Сонячного Щита",
        ruler=None, traits=["martial", "pious"],
        note="Твердиня важких лицарів Сонячного Щита.",
    ),
    "Kinia": dict(
        uk="Республіка Кінія", cont="Кірос", capital="Мебінг", coins="Мебінзький Флорин",
        gov="Вільне купецьке місто-республіка",
        ruler=("Купецька Рада Мебінга", "collective"),
        traits=["mercantile", "cautious"],
        note="Перехрестя доріг між Скіпом та Бертом.",
    ),
    "God": dict(
        uk="Королівство Бога", cont="Кірос", capital="Клітрерінг", coins="Срібний Псалом",
        gov="Фанатична чернечо-військова теократія",
        ruler=("Священний Синод", "collective"),
        traits=["pious", "inquisitorial", "warlike"],
        note="Вогняна теократія півдня Кіросу; кожен громадянин — воїн віри.",
    ),
    "Mania": dict(
        uk="Королівство Манія", cont="Кірос", capital="Бермінглі", coins="Вогняний Статер",
        gov="Фанатична вогняна теократія",
        ruler=("Рада Полум'я", "collective"),
        traits=["pious", "warlike", "besieged"],
        note="Південна вогняна теократія на межі Демонічного Розлому.",
    ),
    "Kiverland": dict(
        uk="Ківерійська Теократія", cont="Кірос", capital="Ротінгтон", coins="Вагове срібло",
        gov="Теократичний домініон півдня",
        ruler=None, traits=["pious", "besieged"],
        note="Південні крижані рубежі Кіросу.",
    ),
    "Kjeland": dict(
        uk="К'єландська Теократія", cont="Кірос", capital="Гімсмар", coins="Вагове срібло",
        gov="Теократія ярлів і шаманів морозних духів",
        ruler=None, traits=["pious", "warlike"],
        note="Південні льодовикові береги; боротьба проти крижаних драконів і немертвих велетнів.",
    ),
    "Khiz": dict(
        uk="Хізанська Теократія", cont="Кірос", capital="Шатіз", coins="Рунне срібло",
        gov="Підземний печерний домініон",
        ruler=None, traits=["pious", "technocratic"],
        note="Хранителі підземних рунних бар'єрів біля Сулкуна.",
    ),
    "Cre": dict(
        uk="Велике герцогство Кре", cont="Кірос", capital="Бландфорд", coins="Вестенський Шилінг",
        gov="Вільна земля Вестену",
        ruler=None, traits=["naval", "mercantile"],
        note="Східний архіпелаг Кіросу, зв'язок з Турсом.",
    ),
    "Feland": dict(
        uk="Велике герцогство Феланд", cont="Кірос", capital="Дармут", coins="Вестенський Шилінг",
        gov="Вільна земля Вестену",
        ruler=None, traits=["naval", "cautious"],
        note="Острівно-проливна держава на сході Кіросу.",
    ),
    "Bridland": dict(
        uk="Єпархія Брідланд", cont="Кірос", capital="Гармінг", coins="Вестенський Шилінг",
        gov="Теократія земель Вестену",
        ruler=None, traits=["pious", "naval"],
        note="Церковна автономія східних півостровів Кіросу.",
    ),
    "Newland": dict(
        uk="Велике герцогство Ньюланд", cont="Кірос", capital="Аксбро", coins="Вестенський Шилінг",
        gov="Вільна земля Вестену",
        ruler=None, traits=["naval", "warlike"],
        note="Морський форпост східного Кіросу.",
    ),
    "Mirati": dict(
        uk="Республіка Міраті", cont="Кірос", capital="Баталфод", coins="Міратський Дукат",
        gov="Морська торгова республіка",
        ruler=("Рада Портів Міраті", "collective"),
        traits=["naval", "mercantile"],
        note="Найбільший торговий порт північно-західного Кіросу.",
    ),
    "Church of Tempus": dict(
        uk="Священна Земля Церкви Темпуса", cont="Кірос", capital="Мартіус", coins="Багряний Статер",
        gov="Острівний військово-релігійний орден",
        ruler=("Архіпаладин Спокути", "male"),
        traits=["pious", "martial", "warlike"],
        note="Притулок залишків Ордену Багряного Знамені; гігантська кузня зачарованої криці.",
    ),
    "Cult of Beshaba": dict(
        uk="Священна Земля Культу Бешаби", cont="Кірос", capital="Весалі", coins="Чорний Статер",
        gov="Острівна фортеця пророчиць Бешаби",
        ruler=("Верховна Пророчиця Чорного Рогу", "female"),
        traits=["pious", "inquisitorial"],
        note="Жриці відводять катавасії від ліній оборони Кіросу.",
    ),
    "Skulls": dict(
        uk="Вільне Місто Черепів", cont="Кірос", capital="The City of Skulls", coins="Кістяний Жетон",
        gov="Нейтральне місто-держава",
        ruler=("Магістрат Черепів", "collective"),
        traits=["cautious", "mercantile"],
        note="Нейтральне портово-прикордонне місто на межі земель.",
    ),
}

# Імена: склади за культурами карти (для решти правителів)
CULTURE_SYLLABLES = {
    "Durinn":    (["Дур", "Бор", "Гім", "Тор", "Ґрім"], ["рін", "дін", "мар", "бул", "дур"]),
    "Enlandic":  (["Ед", "Ґер", "Вільм", "Освальд", "Рід"], ["вард", "рік", "мунд", "ольф", "лін"]),
    "Keltan":    (["Кей", "Брен", "Ґвін", "Маб", "Ніал"], ["ддрін", "ан", "ог", "віс", "ар"]),
    "Mercian":   (["Мер", "Аль", "Ген", "Уль", "Бер"], ["сіан", "рік", "ольд", "він", "рам"]),
    "Westen":    (["Вес", "Ґаб", "Лю", "Ан", "Жак"], ["тен", "ріель", "довік", "туан", "мон"]),
    "Trow":      (["Тро", "Мол", "Ґор", "Рок", "Зуб"], ["ґо", "вар", "бок", "дул", "нак"]),
    "Schwarzen": (["Шварц", "Ґотт", "Ульх", "Вольф", "Ґунт"], ["ґанґ", "рах", "хельм", "бальд", "ер"]),
    "Luarian":   (["Луар", "Анрі", "Ґасп", "Оноре", "Бертр"], ["ьєн", "ар", "ан", "ьє", "оньє"]),
    "Aj'Snaga":  (["Ґар", "Мог", "Шак", "Урґ", "Ґаз"], ["ак", "душ", "наґ", "ґрім", "бук"]),
    "Kobblin":   (["Кіб", "Нік", "Ґоб", "Тіц", "Фіз"], ["лі", "бік", "нок", "зак", "ту"]),
    "Yotunn":    (["Йот", "Ґрі", "Тюр", "Ульв", "Скьол"], ["унн", "мнір", "ґард", "ульф", "дор"]),
    "Romian":    (["Ром", "Кай", "Люц", "Мар", "Гай"], ["улус", "ілій", "іан", "ій", "ент"]),
    "Norse":     (["Рагн", "Ейр", "Бйорн", "Гуннар", "Свен"], ["ар", "ік", "ульф", "сон", "ольд"]),
    "Rakhnid":   (["Рах", "Зах", "Мар", "Касс", "Іл"], ["нід", "рак", "ан", "хір", "драх"]),
    "Nortumbic": (["Нор", "Едґар", "Етель", "Осв", "Гар"], ["вальд", "ред", "ульф", "рік", "олд"]),
    "Wildlands": (["Дик", "Ґор", "Кар", "Бру", "Тал"], ["ар", "ум", "ак", "ог", "ін"]),
}

RULER_TRAITS = {
    "warlike":       dict(war=1.8, trade=0.9, tax=1.0, label="Войовничий"),
    "mercantile":    dict(war=0.6, trade=1.4, tax=0.9, label="Купецький"),
    "pious":         dict(war=1.0, trade=0.9, tax=1.05, label="Благочестивий"),
    "cautious":      dict(war=0.5, trade=1.1, tax=0.95, label="Обачний"),
    "reformer":      dict(war=0.8, trade=1.2, tax=1.0, label="Реформатор"),
    "tyrant":        dict(war=1.4, trade=0.8, tax=1.35, label="Тиран"),
    "industrial":    dict(war=1.1, trade=1.2, tax=1.05, label="Індустріальний"),
    "technocratic":  dict(war=1.0, trade=1.1, tax=1.0, label="Технократичний"),
    "feudal":        dict(war=1.2, trade=0.85, tax=0.95, label="Феодальний"),
    "martial":       dict(war=1.4, trade=0.9, tax=1.0, label="Лицарський"),
    "naval":         dict(war=1.0, trade=1.3, tax=0.95, label="Морський"),
    "whaling":       dict(war=0.9, trade=1.2, tax=0.95, label="Китобійний"),
    "desert":        dict(war=0.9, trade=1.2, tax=1.0, label="Пустельний"),
    "smuggling":     dict(war=0.7, trade=1.3, tax=0.85, label="Контрабандний"),
    "inquisitorial": dict(war=1.3, trade=0.8, tax=1.1, label="Інквізиційний"),
    "besieged":      dict(war=1.6, trade=0.8, tax=1.15, label="Облоговий"),
}
RANDOM_TRAIT_POOL = ["warlike", "mercantile", "pious", "cautious", "reformer", "tyrant"]

_TRANSLIT = [
    ("shch", "щ"), ("sch", "ш"), ("ch", "ч"), ("sh", "ш"), ("zh", "ж"), ("kh", "х"),
    ("th", "т"), ("ph", "ф"), ("ck", "к"), ("qu", "кв"), ("ou", "у"), ("ee", "і"),
    ("oo", "у"), ("ie", "і"), ("ia", "ія"), ("ya", "я"), ("yu", "ю"), ("ts", "ц"),
    ("a", "а"), ("b", "б"), ("c", "к"), ("d", "д"), ("e", "е"), ("f", "ф"), ("g", "г"),
    ("h", "г"), ("i", "і"), ("j", "дж"), ("k", "к"), ("l", "л"), ("m", "м"), ("n", "н"),
    ("o", "о"), ("p", "п"), ("q", "к"), ("r", "р"), ("s", "с"), ("t", "т"), ("u", "у"),
    ("v", "в"), ("w", "в"), ("x", "кс"), ("y", "і"), ("z", "з"), ("'", "'"),
]


def translit(name: str) -> str:
    s = name.lower()
    out, i = [], 0
    while i < len(s):
        for lat, uk in _TRANSLIT:
            if s.startswith(lat, i):
                out.append(uk)
                i += len(lat)
                break
        else:
            out.append(s[i])
            i += 1
    r = "".join(out)
    return r[:1].upper() + r[1:]


GOV_PARAMS = {
    "Monarchy": dict(stab_base=62, war_tolerance=1.0, tax_norm=1.0),
    "Republic": dict(stab_base=58, war_tolerance=0.8, tax_norm=0.9),
    "Theocracy": dict(stab_base=66, war_tolerance=1.1, tax_norm=1.05),
    "Union": dict(stab_base=55, war_tolerance=0.7, tax_norm=0.9),
}

DIPLO_SCORE = {
    "Ally": 85, "Friendly": 55, "Neutral": 5, "Unknown": 0, "Suspicion": -25,
    "Rival": -50, "Enemy": -80, "Suzerain": 60, "Vassal": 60, "x": 0,
}
DIPLO_LABEL_UK = {
    "Ally": "Союзники", "Friendly": "Дружні", "Neutral": "Нейтральні",
    "Unknown": "Невідомі", "Suspicion": "Підозра", "Rival": "Суперники",
    "Enemy": "Вороги", "Suzerain": "Сюзерен", "Vassal": "Васал",
}

# ----------------------------------------------------------------------------
# Гільдії та організації зі сховища
# ----------------------------------------------------------------------------
GUILDS = [
    dict(id="artas", name="Міжнародна гільдія «Артас»", kind="merchant", home="Nar'tunek", home_state="Athas",
         goods=[26, 27, 62, 63], wealth=1200, power=1.4,
         note="Серце світової фінансової системи, базується в Атасі та портах Турсу (Ескрін). Ранги: Мідь→Срібло→Золото→Платина→Електрум."),
    dict(id="makash", name="Караванна Ліга Макаша", kind="merchant", home="Nar'tunek", home_state="Athas",
         goods=[25, 27, 18, 20], wealth=450, power=1.1,
         note="Старий Макаш: транспорт екзотичних товарів, магічних компонентів і реліквій між Німаном, степами Адж'Снага та Атасом."),
    dict(id="night_gold", name="«Нічне Золото»", kind="shadow", home="Escren", home_state="Nimanchia",
         goods=[8, 7, 23], wealth=340, power=0.9, note="Голова — Хальт Кайлос; тіньовий обіг золота й коштовностей."),
    dict(id="golden_dune", name="Ліга Оаз «Золотий Бархан»", kind="merchant", home="Shriazi", home_state="Lial",
         goods=[16, 25, 27, 26, 20], wealth=560, power=1.2,
         note="Монополія на каравани через Великі Дюни; шейх Надір аль-Шріазі."),
    dict(id="north_harpoon", name="Синдикат «Північний Гарпун»", kind="merchant", home="Mith'jess", home_state="Nagen",
         goods=[37, 29, 11], wealth=420, power=1.05,
         note="Китобійний промисел, ворвань, моржова кістка й реліктовий лід; Торольд Морозоборець."),
    dict(id="common_cause", name="Гільдія Спільної Справи", kind="craft", home="Nesploy", home_state="Nimanchia",
         goods=[58, 59], wealth=280, power=0.85, note="Ремісничий союз Несплоя."),
    dict(id="ustivaltsu", name="Цех Зброярів Устівальцу", kind="craft", home="Bouranvile", home_state="Ondia",
         goods=[59, 61, 4], wealth=250, power=0.85, note="Гірничо-зброярський цех Ондії."),
    dict(id="gear_senate", name="«Шестерня Сенату» Несплоя", kind="craft", home="Nesploy", home_state="Nimanchia",
         goods=[58, 60, 61], wealth=410, power=1.05, note="Технократична гільдія інженерів при Залізному Сенаті."),
    dict(id="spiders", name="Нічні Павуки Ескріна", kind="shadow", home="Escren", home_state="Nimanchia",
         goods=[31, 27], wealth=140, power=0.7, note="Тіньова мережа порту Ескрін, підкуповує портову варту."),
    dict(id="zkhoch", name="Асасини Оази Зхоч", kind="shadow", home="Shriazi", home_state="Lial",
         goods=[], wealth=110, power=0.65, note="Гільдія вбивць пустелі."),
    dict(id="conclave_towers", name="Конклав Башт Вищого Чародійства", kind="arcane", home="Mont", home_state="Nimanchia",
         goods=[49, 50, 51, 25], wealth=780, power=1.25,
         note="Об'єднання Білої (Солінарі), Червоної (Лунітарі) та Головної Чорної Башти (Нуітарі). Закон Єдності та Випробування."),
    dict(id="doppel_guild", name="Гільдія Доппельзольднерів Берту", kind="military", home="Grimtiba", home_state="Burt",
         goods=[4, 59, 54], wealth=390, power=1.0,
         note="Елітні найманці-мечники Кіросу з фламбергами; експортують ветеранів крізь шторми океану."),
]

# Найманці
MERCENARIES = [
    dict(id="grey_cloaks", name="Братство Сірих Плащів", size=2400, fee_per_head=1.2, home_state="Athas", unit="infantry"),
    dict(id="scorpions", name="Вільна Рота Скорпіонів", size=1800, fee_per_head=1.4, home_state="Lial", unit="archers"),
    dict(id="iron_griffons", name="Залізні Грифони Німану", size=3200, fee_per_head=1.6, home_state="Nimanchia", unit="infantry"),
    dict(id="doppelsoldners", name="Вільний Полк Доппельзольднерів Берту", size=2000, fee_per_head=1.8, home_state="Burt", unit="infantry"),
]

# Лицарські / релігійні ордени
ORDERS = [
    dict(id="silver_griffon", name="Орден Срібного Грифона", state="Ondia", strength=900, unit="cavalry"),
    dict(id="sacred_ray", name="Лицарі Священного Променя Донії", state="Donia", strength=700, unit="cavalry"),
    dict(id="crimson_redemption", name="Паладини Спокути (Орден Багряного Знамені)", state="Church of Tempus", strength=850, unit="cavalry"),
    dict(id="sun_shield", name="Лицарі Сонячного Щита", state="Cleore", strength=600, unit="cavalry"),
    dict(id="iconoclasts", name="Іконоборці (мисливці на нежить)", state=None, strength=400, unit="infantry"),
]

# ----------------------------------------------------------------------------
# Таблиця подій
# ----------------------------------------------------------------------------
EVENT_TABLE = {
    # --- природа
    "drought":          dict(scope="state", weight=1.0, cat="nature", dur=(4, 10), sev=(1, 3)),
    "flood":            dict(scope="state", weight=0.8, cat="nature", dur=(2, 5), sev=(1, 3)),
    "bumper_harvest":   dict(scope="state", weight=1.0, cat="nature", dur=(3, 6), sev=(1, 2)),
    "locusts":          dict(scope="state", weight=0.35, cat="nature", dur=(2, 5), sev=(2, 3)),
    "harsh_winter":     dict(scope="state", weight=0.7, cat="nature", dur=(3, 5), sev=(1, 3)),
    "sea_storm":        dict(scope="market", weight=0.8, cat="nature", dur=(1, 3), sev=(1, 3)),
    "earthquake":       dict(scope="burg", weight=0.25, cat="nature", dur=(3, 8), sev=(1, 3)),
    "volcano":          dict(scope="marker", weight=0.15, cat="nature", dur=(6, 18), sev=(2, 3)),
    "wildfire":         dict(scope="burg", weight=0.4, cat="nature", dur=(2, 4), sev=(1, 2)),
    # --- хвороби
    "plague":           dict(scope="market", weight=0.35, cat="disease", dur=(4, 12), sev=(2, 3)),
    "cattle_murrain":   dict(scope="state", weight=0.45, cat="disease", dur=(3, 7), sev=(1, 2)),
    # --- економіка
    "gold_rush":        dict(scope="burg", weight=0.35, cat="economy", dur=(6, 18), sev=(1, 3)),
    "mine_collapse":    dict(scope="burg", weight=0.35, cat="economy", dur=(4, 10), sev=(1, 2)),
    "piracy_surge":     dict(scope="market", weight=0.8, cat="economy", dur=(3, 9), sev=(1, 3)),
    "bandit_roads":     dict(scope="state", weight=0.8, cat="economy", dur=(3, 8), sev=(1, 3)),
    "market_panic":     dict(scope="market", weight=0.5, cat="economy", dur=(1, 3), sev=(1, 3)),
    "guild_strike":     dict(scope="burg", weight=0.5, cat="economy", dur=(1, 3), sev=(1, 2)),
    "trade_boom":       dict(scope="market", weight=0.7, cat="economy", dur=(3, 8), sev=(1, 2)),
    "tech_advance":     dict(scope="state", weight=0.3, cat="economy", dur=(12, 36), sev=(1, 2)),
    "caravan_lost":     dict(scope="edge", weight=0.6, cat="economy", dur=(1, 2), sev=(1, 2)),
    # --- політика
    "succession_crisis": dict(scope="state", weight=0.4, cat="politics", dur=(3, 9), sev=(1, 3)),
    "noble_conspiracy": dict(scope="state", weight=0.4, cat="politics", dur=(2, 6), sev=(1, 3)),
    "peasant_revolt":   dict(scope="state", weight=0.5, cat="politics", dur=(3, 8), sev=(1, 3)),
    "royal_wedding":    dict(scope="pair", weight=0.5, cat="politics", dur=(0, 0), sev=(1, 1)),
    "border_incident":  dict(scope="pair", weight=0.9, cat="politics", dur=(0, 0), sev=(1, 2)),
    "trade_embargo":    dict(scope="pair", weight=0.35, cat="politics", dur=(6, 18), sev=(1, 2)),
    "tax_reform":       dict(scope="state", weight=0.45, cat="politics", dur=(0, 0), sev=(1, 1)),
    "coup":             dict(scope="state", weight=0.12, cat="politics", dur=(2, 6), sev=(2, 3)),
    # --- магія та міфічне (епоха Третьої Зорі, Попелясті пустки, Геракліт)
    "monster_horde":    dict(scope="state", weight=0.5, cat="magic", dur=(2, 6), sev=(1, 3)),
    "dungeon_breach":   dict(scope="burg", weight=0.5, cat="magic", dur=(2, 8), sev=(1, 3)),
    "dragon_attack":    dict(scope="burg", weight=0.12, cat="magic", dur=(3, 9), sev=(2, 3)),
    "mana_surge":       dict(scope="state", weight=0.3, cat="magic", dur=(3, 9), sev=(1, 2)),
    "artifact_found":   dict(scope="state", weight=0.2, cat="magic", dur=(0, 0), sev=(1, 1)),
    "undead_incursion": dict(scope="state", weight=0.4, cat="magic", dur=(2, 8), sev=(1, 3)),
    "tower_breakthrough": dict(scope="state", weight=0.25, cat="magic", dur=(12, 30), sev=(1, 2)),
    "black_rust":       dict(scope="state", weight=0.22, cat="magic", dur=(4, 9), sev=(1, 3)),
}
EVENT_TITLES = {
    "drought": "Посуха", "flood": "Повінь", "bumper_harvest": "Рясний врожай",
    "locusts": "Нашестя сарани", "harsh_winter": "Люта зима", "sea_storm": "Морська буря",
    "earthquake": "Землетрус", "volcano": "Виверження вулкана", "wildfire": "Велика пожежа",
    "plague": "Епідемія", "cattle_murrain": "Мор худоби", "gold_rush": "Золота лихоманка",
    "mine_collapse": "Обвал у копальні", "piracy_surge": "Сплеск піратства",
    "bandit_roads": "Розбійники на шляхах", "market_panic": "Паніка на ринку",
    "guild_strike": "Страйк гільдій", "trade_boom": "Торговий бум",
    "tech_advance": "Ремісниче відкриття", "caravan_lost": "Пограбований караван",
    "succession_crisis": "Криза престолонаслідування", "noble_conspiracy": "Змова знаті",
    "peasant_revolt": "Селянський заколот", "royal_wedding": "Династичний шлюб",
    "border_incident": "Прикордонний інцидент", "trade_embargo": "Торговельне ембарго",
    "tax_reform": "Податкова реформа", "coup": "Державний переворот",
    "monster_horde": "Орда монстрів", "dungeon_breach": "Прорив підземелля",
    "dragon_attack": "Напад дракона", "mana_surge": "Сплеск мани",
    "artifact_found": "Знахідка артефакта", "undead_incursion": "Вторгнення нежиті",
    "tower_breakthrough": "Прорив магічної башти", "black_rust": "Спалах «Чорної Іржі»",
}

# ----------------------------------------------------------------------------
# Сценарій Четвертого Походу на Кірос
# ----------------------------------------------------------------------------
CRUSADE = dict(
    name="Четвертий Великий Похід на Кірос",
    sponsor_states=["Nimanchia", "Ondia", "Donia", "Lando", "Nagen"],
    start_after_months=6,
    muster_months=18,
    sail_months=4,
    campaign_months=24,
    tax_boost=1.25,
    demand_goods=[53, 52, 59, 64, 56, 18],  # кораблі, вітрила, зброя, консерви, бочки, коні
    demand_units=60.0,
    base_success=0.42,
)
