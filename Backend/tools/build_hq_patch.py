"""Патч страницы «Поощрения» в штабе (главное меню) под Project Remaster v17.

Remaster поменял содержимое деревьев поощрений, но не меню: штаб показывал ванильные иконки,
названия и описания. К тому же в Remaster ветки «Способности» (51x) и «Ком. отделения» (52x)
у каждого класса свои, а на странице они общие.

Что делает скрипт (все исходники берёт из установленной игры, ничего не скачивает):
  1. Читает деревья Remaster (Kits_server.zip) и ванили, сопоставляет ячейки.
  2. mainMenu.dfm (Flash 7, XOR 0BADF00D): для каждой вкладки класса K делает копии кнопок,
     которые грузят иконки из images/unlockK/, и заменяет ключи строк на NAME_HQK_UL_<id> /
     DESCRIPTION_HQK_UL_<id> (замены той же длины, ID поощрений не меняются).
  3. Генерирует иконки (обычная, _locked, _hi) для каждой вкладки и для общей папки
     images/unlocks/ (её использует экран конца раунда, где колонка 5xx одна на все классы).
  4. Дописывает строки в Localization/strings.csv Remaster (оригинал сохраняется рядом).
  5. Кладёт Objects/Menu_selfhost_hq_server.zip (меню) и Objects/Menu_selfhost_hq_client.zip
     (картинки) и подключает их первыми строками ServerArchives.con / ClientArchives.con.

    .venv\\Scripts\\python.exe tools\\build_hq_patch.py              # собрать и установить
    .venv\\Scripts\\python.exe tools\\build_hq_patch.py --preview DIR # только картинки-превью
    .venv\\Scripts\\python.exe tools\\build_hq_patch.py --uninstall   # вернуть как было
"""

import argparse
import io
import re
import shutil
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import imagelib as il  # noqa: E402
from bf2142srv import config  # noqa: E402

GAME = config.load().game_dir  # папка игры (клиента): [paths] game в config.toml
VANILLA = GAME / "mods" / "bf2142"
REMASTER = GAME / "mods" / "Project_Remaster_v17"
SERVER_ZIP = "Menu_selfhost_hq_server.zip"
CLIENT_ZIP = "Menu_selfhost_hq_client.zip"
STRINGS_BACKUP = "strings.csv.selfhost_orig"
KITS = {1: "recon", 2: "assault", 3: "engineer", 4: "support"}
KIT_TEXT = {1: "TEXT_kit_recon", 2: "TEXT_kit_assault", 3: "TEXT_kit_engineer", 4: "TEXT_kit_support"}
FACTION_TEXT = {"EU": "HEADER_eu", "PAC": "HEADER_pac"}
SIZES = {"s": (30, 30), "m": (45, 45), "l": (102, 45)}
DFM_KEY = bytes([0x0B, 0xAD, 0xF0, 0x0D])
# Варианты ЕС/ПАК в описании идут одной строкой ([ЕС - А] ... [ПАК - Б] ...). Разнести их по
# строкам в меню SwiffPlayer не удалось (проверено в игре 2026-10-06): текст с \r или \n поле не
# принимает ни из strings.csv, ни из кода; второй TextContainer (duplicateMovieClip или attachMovie
# в getUnlockInfo) остаётся пустым. Вызов setLocID из конца getUnlockInfo при этом работает.

# Тексты для предметов, у которых в Remaster только английская строка (название/описание
# прямо в .tweak). Английский берётся из Remaster, здесь — перевод.
RU = {
    "eu_duplex_shotgun_smk": ("Дробовик «Дуплекс» SMK",
        "Эта модификация дробовика «Дуплекс» стреляет специальными зарядами, которые при попадании ставят "
        "плотную дымовую завесу. Идеальна, чтобы перекрыть обзор противнику или прикрыть отход."),
    "eu_seburo_sr": ("Крупнокалиберная винтовка «Себуро»",
        "Крупнокалиберная винтовка «Себуро» с продольно-скользящим затвором создана для предельной скорости "
        "пули и точности. Благодаря продвинутой оптике она с дальней дистанции поражает пехоту и "
        "легкобронированные цели."),
    "as_rsvk_taganrog": ("Крупнокалиберная винтовка «Таганрог-II»",
        "«Таганрог-II» — экспериментальная крупнокалиберная винтовка ПАК для сокрушительного огня на "
        "предельных дистанциях. Улучшенная оптика и полуавтоматический режим огня позволяют уверенно "
        "поражать легкобронированные цели."),
    "as_ar_vostok": ("Карабин «Восток»", None),
    "unl_sni_lasergun": ("Автоматическая снайперская винтовка «Шортбоу»",
        "Автоматическая снайперская винтовка «Шортбоу» создана для боя на средних дистанциях: быстрые и "
        "точные выстрелы, когда цель нужно снять издалека и без промедления."),
    "eu_duplex_shotgun": ("Дробовик «Дуплекс»",
        "Компактный дробовик «Дуплекс» бьёт очень мощно на ближней дистанции. Заменяет личное оружие, когда "
        "вы командир отделения."),
    "smg_pistol": ("Автоматический пистолет «Корсаков»",
        "«Корсаков-АП» — компактный автоматический пистолет с магазином на 20 патронов, любимый спецназом ПАК "
        "при абордаже титанов. Заменяет личное оружие, когда вы командир отделения."),
    "unl_throwing_knife": ("Метательные ножи",
        "Стандартные метательные ножи, которые так любят диверсанты. Клинок в умелых руках не менее "
        "смертоносен, чем пуля."),
    "eu_gauss_rifle": ("Штурмовая винтовка «Скади MK2»",
        "«Скади MK2» — штурмовая винтовка последнего поколения с огромной начальной скоростью пули и "
        "барабанным магазином. При долгой стрельбе остерегайтесь перегрева."),
    "handgun_eu_omnicorp_auto9": ("Пистолет «Автомаг Марк 9»",
        "«Автомаг Марк 9» — мощный пистолет элитных частей ЕС. За огромную останавливающую силу приходится "
        "платить сильной отдачей. Заменяет личное оружие, когда вы состоите в отделении."),
    "handgun_magnum": ("Револьвер «Магнум 357»",
        "«Магнум 357» — тактический револьвер с глушителем для точных выстрелов на большой дистанции. "
        "Заменяет личное оружие, когда вы состоите в отделении."),
    "unl_auto_gl": ("Гранатомёт «Мэдлок»",
        "«Мэдлок» стреляет магнитными самонаводящимися гранатами, которые преследуют движущуюся технику и "
        "взрываются через 5 секунд. Барабан на шесть выстрелов превращает вражескую технику в металлолом."),
    "eu_rorsch_mk_v": ("Противотанковая винтовка «Рорш MK-V»",
        "«Рорш MK-V» — новейшее противотанковое оружие на электромагнитном разгоне. Перед выстрелом нужна "
        "зарядка 2,5 секунды, зато снаряд на огромной скорости бьёт с дальней дистанции."),
    "proton_smg": ("Пистолет-пулемёт «Протон»",
        "Лёгкий и компактный «Протон» — выбор инженеров. Высокий темп стрельбы и магазин на 45 патронов "
        "делают его идеальным для ближнего боя, не лишая солдата мобильности."),
    "type19": ("Пистолет-пулемёт «Тип-19 Сальмоса»",
        "Названный в честь ядовитой южнокорейской гадюки, «Тип-19 Сальмоса» любим инженерами спецподразделений "
        "ПАК. Магазин на 50 патронов делает его особенно хорошим в ближнем бою."),
    "unl_shotgunrdx": (None,
        "Штурмовой дробовик «Кларк-12» — компактное и мощное оружие ближнего боя с барабанным магазином. "
        "Быстрый и разрушительный огонь в тесных помещениях."),
    "eu_knight_mkii": ("Ручной пулемёт «Найт MK-II»",
        "«Найт MK-II» — пулемёт для подавления пехоты с магазином на 200 патронов и массивным стволом для "
        "долгой непрерывной стрельбы. Учтите долгое охлаждение, если оружие перегреется."),
    "eu_jackhammer": ("Дробовик «Хаммерхед TB2»",
        "«Хаммерхед TB2» — универсальный помповый дробовик под пулевые патроны, смертоносный и вблизи, и на "
        "дальней дистанции."),
    "sht_vega": ("Дробовик «Распата-99»",
        "«Распата-99» — дробовик армии ПАК, созданный для точности и мощи. Месть лучше всего подавать "
        "пулевыми патронами."),
}
# Один и тот же предмет в разной окраске у фракций: тексты берём у первого.
SAME_ITEM = {"bp1_expl_shotgunpac": "bp1_expl_shotgun"}
# Короткие имена для заголовка, когда у ЕС и ПАК в ячейке разные предметы ("А / Б").
SHORT = {
    "eu_seburo_sr": ("Seburo AMR", "Себуро"),
    "as_rsvk_taganrog": ("Taganrog-II AMR", "Таганрог-II"),
    "unl_sni_lasergun": ("Shortbow ASR", "Шортбоу"),
    "eu_knight_mkii": ("Knight MK-II", "Найт MK-II"),
    "eu_jackhammer": ("TB2 Hammerhead", "Хаммерхед TB2"),
    "sht_vega": ("Raspata-99", "Распата-99"),
    "handgun_eu_omnicorp_auto9": ("Automag Mark 9", "Автомаг Марк 9"),
    "handgun_magnum": ("Magnum 357", "Магнум 357"),
    "proton_smg": ("Proton SMG", "Протон"),
    "type19": ("Type-19 Salmosa", "Тип-19 Сальмоса"),
    "as_ar_vostok": ("Vostok Carbine", "Карабин Восток"),
}
CLASS_WEAPON = {"English": "Class weapon", "Russian": "Оружие класса"}


# ============================================================ исходные данные игры

def read_zip_text(zf, name):
    return zf.read(name).decode("latin-1")


def parse_kits(zpath):
    """{(kit 1..4, unlock id): {"EU"/"PAC": template}} для деревьев одного архива."""
    branches = {None: (0, 1), "UB_Second": (0, 2), "UB_Player": (5, 1), "UB_SquadLeader": (5, 2)}
    out = {}
    zf = zipfile.ZipFile(zpath)
    for name in zf.namelist():
        if not name.lower().endswith(".con"):
            continue
        kit = index = None
        conts, cur = {}, None
        for line in read_zip_text(zf, name).splitlines():
            s = line.strip()
            m = re.match(r"(?i)ObjectTemplate\.create\s+(\S+)\s+(\S+)", s)
            if m:
                typ, tname = m.groups()
                cur = None
                if typ.lower() == "kit":
                    kit = tname
                elif typ.lower() == "itemcontainer":
                    cur = conts[tname] = {"add": [], "level": None, "branch": None}
                continue
            if kit and cur is None:
                m = re.match(r"(?i)ObjectTemplate\.unlockIndex\s+(\d+)", s)
                if m:
                    index = int(m.group(1))
            if cur is not None:
                m = re.match(r"(?i)ObjectTemplate\.(addTemplate|unlockLevel|unlockBranch)\s+(\S+)", s)
                if m:
                    key, val = m.group(1).lower(), m.group(2)
                    if key == "addtemplate":
                        cur["add"].append(val)
                    elif key == "unlocklevel":
                        cur["level"] = int(val)
                    else:
                        cur["branch"] = val
        if kit is None or index is None:
            continue
        faction = "EU" if kit.lower().startswith("eu") else "PAC"
        for c in conts.values():
            if c["level"] is None or c["level"] >= 10 or not c["add"]:
                continue  # 15 = автозамена ножа, не ячейка дерева
            first, tree = branches[c["branch"]]
            uid = f"{first or index + 1}{tree}{c['level'] + 1}"
            out.setdefault((index + 1, uid), {})[faction] = c["add"][0]
    return out


def parse_weapon_huds(zpaths):
    """template.lower() -> поля weaponHud (hudName, descrString, unlockIcon, ...)."""
    huds = {}
    for zp in zpaths:
        zf = zipfile.ZipFile(zp)
        for name in zf.namelist():
            if not name.lower().endswith((".con", ".tweak")):
                continue
            cur = None
            for line in read_zip_text(zf, name).splitlines():
                s = line.strip()
                m = re.match(r"(?i)ObjectTemplate\.(?:create|activeSafe)\s+\S+\s+(\S+)", s)
                if m:
                    cur = huds.setdefault(m.group(1).lower(), {})
                    continue
                m = re.match(r"(?i)ObjectTemplate\.weaponHud\.(hudName|descrString|unlockIcon|selectIcon|"
                             r"renderedPicture|weaponIcon)\s+(.*)", s)
                if cur is not None and m:
                    cur.setdefault(m.group(1), m.group(2).strip().strip('"'))
    return huds


# В растровых шрифтах игры (Fonts_client.zip, *.dif) нет «» — – … №, а ё есть не во всех размерах.
FONT_SAFE = str.maketrans({"«": '"', "»": '"', "„": '"', "“": '"', "”": '"', "—": "-", "–": "-",
                           "…": "...", "№": "N", "ё": "е", "Ё": "Е", " ": " ", "\t": " "})


def font_safe(text):
    return re.sub(r" {2,}", " ", text.translate(FONT_SAFE)).strip()


# Сообщения, которые клиент показывает на коды ошибок нашего бэкенда (bf2142srv/fesl.py): в оригинале
# «обратитесь в службу поддержки EA», а правила имён у нас свои. Остальные языки получат английский.
LOGIN_TEXTS = {
    "LOCERROR_accountbanned": {
        "English": "This account has been banned by the server administration.",
        "Russian": "Учетная запись заблокирована администрацией сервера.",
    },
    "LOCERROR_accountnameinvalid": {
        "English": "Names may contain only Latin letters and digits, from 3 to 16 characters.",
        "Russian": "Имя может содержать только латинские буквы и цифры, от 3 до 16 символов.",
    },
}


class Strings:
    """Localization/strings.csv: UTF-16, табы, строки оканчиваются на \\r\\r\\n."""

    def __init__(self, path):
        text = path.read_bytes().decode("utf-16")
        self.eol = "\r\r\n" if "\r\r\n" in text else "\r\n"
        lines = text.split(self.eol)
        self.header = lines[0].split("\t")
        self.langs = self.header[1:]
        self.order, self.rows, self.fixed = [], {}, False
        for line in lines[1:]:
            if not line:
                continue
            f = line.split("\t")
            if f[0] not in self.rows:
                self.order.append(f[0])
            self.rows[f[0]] = f

    @staticmethod
    def unquote(v):
        """Часть строк в файле записана с CSV-кавычками (поле в кавычках, внутри удвоенные), но движок
        их не снимает и показывает как есть, поэтому читаем без кавычек, а пишем просто текст."""
        if len(v) >= 2 and v[0] == v[-1] == '"' and '"' not in v[1:-1].replace('""', ''):
            return v[1:-1].replace('""', '"')
        return v

    def fix_all(self):
        """Ошибки локализации во всём файле: CSV-кавычки, которые игра показывает как есть (поле
        в кавычках с удвоенными кавычками внутри), символы, которых нет в русских шрифтах,
        и пропавшее «(золото)» у звания 23. Возвращает число исправленных строк."""
        ru = self.langs.index("Russian") + 1
        fixed = 0
        for key, f in self.rows.items():
            new = [f[0]] + [self.unquote(v) for v in f[1:]]
            if len(new) > ru:
                new[ru] = new[ru].translate(FONT_SAFE)
            if key == "RANK_23" and "(" not in new[ru]:
                new[ru] += " (золото)"
            if new != f:
                self.rows[key] = new
                fixed += 1
        self.fixed = True  # дальше get() кавычки уже не снимает
        return fixed

    def get(self, key):
        """{язык: текст} или None."""
        f = self.rows.get(key)
        if not f:
            return None
        clean = (lambda v: v) if self.fixed else self.unquote
        return {lang: clean(f[i + 1]) if i + 1 < len(f) else "" for i, lang in enumerate(self.langs)}

    def set(self, key, texts):
        if key not in self.rows:
            self.order.append(key)
        self.rows[key] = [key] + [font_safe(texts.get(lang) or texts["English"]) for lang in self.langs]

    def dump(self):
        lines = ["\t".join(self.header)] + ["\t".join(self.rows[k]) for k in self.order]
        return (self.eol.join(lines) + self.eol).encode("utf-16-le")


class Textures:
    """Поиск файлов меню без учёта регистра: Remaster, затем ваниль."""

    def __init__(self, zpaths):
        self.index = {}
        for zp in zpaths:
            zf = zipfile.ZipFile(zp)
            for n in zf.namelist():
                self.index.setdefault(n.lower(), (zf, n))

    def read(self, path):
        hit = self.index.get(path.replace("\\", "/").lower())
        return hit[0].read(hit[1]) if hit else None

    def image(self, path):
        data = self.read(path)
        return il.read_any(path, data) if data else None


# ============================================================ предметы

class Item:
    def __init__(self, template, names, descs, icon, vanilla_uid):
        self.template, self.names, self.descs, self.icon = template, names, descs, icon
        self.vanilla_uid = vanilla_uid  # ячейка, где этот предмет был в ванили (или None)


def build_items(slots, vanilla_slots, huds, strings, textures):
    """Каталог предметов: шаблон -> Item (тексты на всех языках и исходная картинка)."""
    vanilla_where = {}
    for (kit, uid), facs in vanilla_slots.items():
        for tpl in facs.values():
            vanilla_where.setdefault(tpl.lower(), uid)
    items = {}
    for facs in slots.values():
        for tpl in facs.values():
            key = SAME_ITEM.get(tpl.lower(), tpl.lower())
            if tpl.lower() in items:
                continue
            uid = vanilla_where.get(key)
            if uid:  # предмет есть в ванили: её переводы на все языки
                names, descs = strings.get(f"NAME_UNLOCK_{uid}"), strings.get(f"DESCRIPTION_UNLOCK_{uid}")
            else:
                hud = huds.get(key, {})
                names = text_field(hud.get("hudName", tpl), strings, RU.get(key, (None, None))[0])
                descs = text_field(hud.get("descrString", ""), strings, RU.get(key, (None, None))[1])
            hud = huds.get(tpl.lower(), {})
            icon = None
            for field in ("unlockIcon", "weaponIcon", "renderedPicture"):
                if hud.get(field):
                    icon = textures.image("hud/texture/" + hud[field])
                    if icon:
                        break
            items[tpl.lower()] = Item(tpl, names, descs, icon, uid)
    return items


def text_field(value, strings, ru):
    """Значение из .tweak — либо ключ локализации, либо английский текст."""
    texts = strings.get(value)
    if texts is None:
        texts = {lang: value for lang in strings.langs}
    if ru:
        texts = dict(texts, Russian=ru)
    return texts


def same_item(eu, pac):
    """ЕС и ПАК получают одно и то же (или фракционные варианты одного ванильного предмета)."""
    return eu is pac or SAME_ITEM.get(pac.template.lower()) == eu.template.lower() or \
        (eu.vanilla_uid is not None and eu.vanilla_uid == pac.vanilla_uid)


def short_name(item, lang):
    short = SHORT.get(item.template.lower())
    if short:
        return short[1] if lang == "Russian" else short[0]
    return item.names[lang]


def slot_texts(facs, items, strings):
    """Название и описание ячейки; если у фракций разные предметы — оба варианта одной строкой."""
    eu, pac = items[facs["EU"].lower()], items[facs["PAC"].lower()]
    if same_item(eu, pac):
        return eu.names, eu.descs
    fac = {f: strings.get(FACTION_TEXT[f]) for f in FACTION_TEXT}
    names, descs = {}, {}
    for lang in strings.langs:
        same_name = eu.names[lang] == pac.names[lang]
        a, b = short_name(eu, lang), short_name(pac, lang)
        names[lang] = eu.names[lang] if same_name else f"{a} / {b}"
        e, p = fac["EU"][lang], fac["PAC"][lang]
        head_e, head_p = (e, p) if same_name else (f"{e} - {a}", f"{p} - {b}")
        descs[lang] = f"[{head_e}] {eu.descs[lang]} [{head_p}] {pac.descs[lang]}"
    return names, descs


def shared_texts(uid, slots, items, strings):
    """Общие строки 5xx (экран конца раунда): по классам, одинаковые — вместе."""
    groups = {}
    for kit in KITS:
        facs = slots[(kit, uid)]
        sig = (facs["EU"].lower(), facs["PAC"].lower())
        groups.setdefault(sig, []).append(kit)
    if len(groups) == 1:
        return slot_texts(slots[(1, uid)], items, strings)
    per = {sig: slot_texts(slots[(kits[0], uid)], items, strings) for sig, kits in groups.items()}
    names, descs = {}, {}
    for lang in strings.langs:
        distinct = [n[lang] for n, _ in per.values()]
        names[lang] = " / ".join(distinct) if len(distinct) == 2 else CLASS_WEAPON.get(lang, CLASS_WEAPON["English"])
        parts = []
        for sig, kits in groups.items():
            who = ", ".join(strings.get(KIT_TEXT[k])[lang] for k in kits)
            parts.append(f"[{who}] {per[sig][0][lang]}.")
        descs[lang] = " ".join(parts)
    return names, descs


# ============================================================ картинки

def hi_background(vanilla_menu):
    """Фон больших картинок. Во всех ванильных *_hi.png он один и тот же (±1 от сжатия), а предметы
    лежат в разных местах, поэтому в каждом пикселе берём самый частый цвет (с допуском)."""
    imgs = [il.read_png(vanilla_menu.read(n)) for n in vanilla_menu.namelist()
            if re.search(r"/unlocks/\d+_hi\.png$", n)]
    w, h = imgs[0][0], imgs[0][1]

    def lum(c):
        return (c[0] * 30 + c[1] * 59 + c[2] * 11) / 100
    px = bytearray(w * h * 4)
    known = [False] * (w * h)
    for y in range(h):
        # края кадра всегда пустые: между ними фон меняется плавно
        left = lum(imgs[0][2][y * w * 4:y * w * 4 + 3])
        right = lum(imgs[0][2][(y * w + w - 1) * 4:(y * w + w - 1) * 4 + 3])
        for x in range(w):
            i = (y * w + x) * 4
            ref = left + (right - left) * x / (w - 1)
            colors = [tuple(img[2][i:i + 3]) for img in imgs]
            bins = {}
            for c in colors:
                key = (c[0] >> 3, c[1] >> 3, c[2] >> 3)
                bins[key] = bins.get(key, 0) + 1

            def votes(key):
                return sum(bins.get((key[0] + a, key[1] + b, key[2] + c), 0)
                           for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1))
            fits = [k for k in bins if votes(k) >= 3 and max(k) - min(k) <= 1  # серый, как фон
                    and abs(lum([v * 8 + 4 for v in k]) - ref) <= 25]
            if not fits:
                continue
            best = max(fits, key=votes)
            near = [c for c in colors if all(abs((v >> 3) - k) <= 1 for v, k in zip(c, best))]
            for ch in range(3):
                px[i + ch] = round(sum(c[ch] for c in near) / len(near))
            px[i + 3] = 255
            known[y * w + x] = True
    # дыры (везде закрыты предметами) заполняем средним по известным соседям
    while not all(known):
        fill = []
        for y in range(h):
            for x in range(w):
                if known[y * w + x]:
                    continue
                around = [(nx, ny) for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
                          if 0 <= nx < w and 0 <= ny < h and known[ny * w + nx]]
                if around:
                    fill.append((x, y, [sum(px[(ny * w + nx) * 4 + ch] for nx, ny in around) // len(around)
                                        for ch in range(3)]))
        for x, y, rgb in fill:
            px[(y * w + x) * 4:(y * w + x) * 4 + 4] = bytes(rgb + [255])
            known[y * w + x] = True
    return w, h, px


def compose(icons, bw, bh, margin=1):
    """Одна или несколько картинок в холсте bw×bh: 2 — друг над другом, 3–4 — сеткой 2×2."""
    icons = [i for i in icons if i is not None]
    canvas = il.new(bw, bh)
    if not icons:
        return canvas
    if len(icons) == 1:
        cells = [(0, 0, bw, bh)]
    elif len(icons) == 2:
        cells = [(0, 0, bw, bh // 2), (0, bh // 2, bw, bh - bh // 2)]
    else:
        hw, hh = bw // 2, bh // 2
        cells = [(0, 0, hw, hh), (hw, 0, bw - hw, hh), (0, hh, hw, bh - hh), (hw, hh, bw - hw, bh - hh)]
    for img, (x, y, w, h) in zip(icons, cells):
        il.paste(canvas, il.fit(img, w, h, margin), x, y)
    return canvas


def make_icons(icons, size, background):
    """(обычная, _locked, _hi) для ячейки размера size из одной/нескольких исходных картинок."""
    w, h = SIZES[size]
    normal = compose(icons, w, h)
    if size == "s":  # маленькие ячейки в ванили — белые пиктограммы
        normal = il.silhouette(normal, (255, 255, 255))
    locked = il.silhouette(normal)
    bw, bh, bpx = background
    hi = (bw, bh, bytearray(bpx))
    il.paste(hi, compose(icons, bw - 16, bh - 8, 2), 8, 4)
    return normal, locked, hi


def slot_icons(facs, items):
    eu, pac = items[facs["EU"].lower()], items[facs["PAC"].lower()]
    return [eu] if same_item(eu, pac) else [eu, pac]


def vanilla_files(menu, uid):
    base = f"External/FlashMenu/images/unlocks/{uid}"
    try:
        return [menu.read(base + suffix) for suffix in (".png", "_locked.png", "_hi.png")]
    except KeyError:
        return None


# ============================================================ Flash-меню

def xor_dfm(data):
    key = DFM_KEY * (len(data) // 4 + 1)
    return bytes(a ^ b for a, b in zip(data, key))


def swf_tags(data, pos, end):
    while pos < end:
        start = pos
        hdr = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        code, ln = hdr >> 6, hdr & 0x3F
        if ln == 0x3F:
            ln = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        yield code, start, pos, ln
        pos += ln
        if code == 0:
            break


DEFINE_TAGS = {2, 6, 7, 10, 11, 14, 20, 21, 22, 32, 33, 34, 35, 36, 37, 39, 46, 48, 60, 75, 83, 84, 87, 90, 91}


def placeobject2(data, body):
    """(позиция id символа или None, имя или None) у PlaceObject2."""
    flags = data[body]
    p = body + 3
    cid_pos = None
    if flags & 0x02:
        cid_pos = p
        p += 2
    bit = [p * 8]

    def bits(n):
        v = 0
        for _ in range(n):
            v = (v << 1) | ((data[bit[0] >> 3] >> (7 - (bit[0] & 7))) & 1)
            bit[0] += 1
        return v
    if flags & 0x04:  # MATRIX
        if bits(1):
            n = bits(5); bits(n); bits(n)
        if bits(1):
            n = bits(5); bits(n); bits(n)
        n = bits(5); bits(n); bits(n)
        p = (bit[0] + 7) >> 3
    if flags & 0x08:  # CXFORMWITHALPHA
        bit[0] = p * 8
        has_add, has_mult, n = bits(1), bits(1), bits(4)
        bits(n * 4 * (has_add + has_mult))
        p = (bit[0] + 7) >> 3
    if flags & 0x10:
        p += 2
    name = None
    if flags & 0x20:
        end = data.index(b"\0", p)
        name = data[p:end].decode("latin-1")
    return cid_pos, name


def tag_list(data, pos, end):
    """[[код, тело, длинный заголовок?], ...] — теги подряд, включая End."""
    out = []
    for code, start, body, ln in swf_tags(data, pos, end):
        out.append([code, bytearray(data[body:body + ln]), data[start] & 0x3F == 0x3F])
    return out


def tag_bytes(code, body, long_header):
    if len(body) < 0x3F and not long_header:
        return struct.pack("<H", code << 6 | len(body)) + bytes(body)
    return struct.pack("<HI", code << 6 | 0x3F, len(body)) + bytes(body)


def patch_menu(dfm):
    """Возвращает (новый mainMenu.dfm, {id символа вкладки: K}, отчёт)."""
    data = xor_dfm(dfm)
    assert data[:3] == b"FWS", "mainMenu.dfm: не SWF после расшифровки"
    nbits = data[8] >> 3
    pos = 8 + (5 + 4 * nbits + 7) // 8 + 4
    root = tag_list(data, pos, len(data))
    sprites, max_id = {}, 0
    for i, (code, body, _) in enumerate(root):
        if code in DEFINE_TAGS:
            max_id = max(max_id, struct.unpack_from("<H", body, 0)[0])
        if code == 39:
            sprites[struct.unpack_from("<H", body, 0)[0]] = i

    def places(inner):
        for code, body, _ in inner:
            if code == 26:
                cid_pos, name = placeobject2(body, 0)
                yield body, cid_pos, name

    inners = {sid: tag_list(root[i][1], 4, len(root[i][1])) for sid, i in sprites.items()}
    # кнопки грузят иконку и подложку, но (в отличие от вкладок) не трогают строки описаний
    buttons = [sid for sid, i in sprites.items()
               if b"images/unlocks/bg_\0" in root[i][1] and b"images/unlocks/\0" in root[i][1]
               and b"NAME_UNLOCK_\0" not in root[i][1]]
    tabs = {}
    for sid in sprites:
        kits = {int(name[9]) for _, _, name in places(inners[sid])
                if name and re.fullmatch(r"mcUnlock_[1-4]\d\d", name)}
        if len(kits) == 1:
            tabs[sid] = kits.pop()
    assert len(buttons) == 3 and len(tabs) >= 4, f"не нашёл кнопки/вкладки: {buttons} {tabs}"

    # копии кнопок для каждой вкладки: images/unlocks/ -> images/unlockK/
    new_ids, copies = {}, []
    for k in sorted(set(tabs.values())):
        for sid in sorted(buttons):
            body = bytearray(root[sprites[sid]][1])
            max_id += 1
            struct.pack_into("<H", body, 0, max_id)
            old = b"images/unlocks/\0"
            assert body.count(old) == 1
            new_ids[(k, sid)] = max_id
            copies.append([39, body.replace(old, f"images/unlock{k}/\0".encode()), True])

    report = []
    for sid, k in sorted(tabs.items()):
        inner, moved, counts = inners[sid], 0, [0, 0, 0]
        for body, cid_pos, name in places(inner):
            if cid_pos is not None and name and name.startswith("mcUnlock_"):
                cid = struct.unpack_from("<H", body, cid_pos)[0]
                if cid in buttons:
                    struct.pack_into("<H", body, cid_pos, new_ids[(k, cid)])
                    moved += 1
        for tag in inner:
            for n, (old, new) in enumerate([(b"images/unlocks/\0", f"images/unlock{k}/\0"),
                                            (b"NAME_UNLOCK_\0", f"NAME_HQ{k}_UL_\0"),
                                            (b"DESCRIPTION_UNLOCK_\0", f"DESCRIPTION_HQ{k}_UL_\0")]):
                new = new.encode()
                assert len(old) == len(new)
                counts[n] += tag[1].count(old)
                tag[1] = tag[1].replace(old, new)
        body = root[sprites[sid]][1][:4] + b"".join(tag_bytes(*t) for t in inner)
        root[sprites[sid]] = [39, body, True]
        report.append(f"вкладка {KITS[k]} (sprite {sid}): кнопок {moved}, замен строк {counts}")
        assert moved >= 16 and counts == [1, 1, 1], report[-1]  # 16 кнопок без Northern Strike, 20 с ним

    last = max(sprites[sid] for sid in buttons)
    root[last + 1:last + 1] = copies
    out = bytearray(data[:pos]) + b"".join(tag_bytes(*t) for t in root)
    struct.pack_into("<I", out, 4, len(out))
    return xor_dfm(bytes(out)), tabs, report


# ============================================================ сборка

def slot_size(uid):
    """Размер ячейки на странице: широкая — оружие классов (x14/x24), маленькая — «Способности»."""
    if uid[0] != "5" and uid[1:] in ("14", "24"):
        return "l"
    return "s" if uid.startswith("51") else "m"


def build(preview_dir=None):
    vanilla_menu = zipfile.ZipFile(VANILLA / "Menu_client.zip")
    strings_path = REMASTER / "Localization" / "strings.csv"
    original = REMASTER / "Localization" / STRINGS_BACKUP
    strings = Strings(original if original.exists() else strings_path)
    print(f"исправлено строк локализации (кавычки, символы, звание 23): {strings.fix_all()}")
    for key, texts in LOGIN_TEXTS.items():
        strings.set(key, texts)

    slots = parse_kits(REMASTER / "Objects" / "Kits_server.zip")
    vanilla_slots = parse_kits(VANILLA / "Objects" / "Kits_server.zip")
    huds = parse_weapon_huds([REMASTER / "Objects" / "Weapons_server.zip", VANILLA / "Objects" / "Weapons_server.zip",
                              VANILLA / "Objects" / "Weapons_bp1_server.zip"])
    textures = Textures([REMASTER / "Objects" / "Menu_client.zip", VANILLA / "Menu_client.zip",
                         VANILLA / "Menu_bp1_client.zip"])
    items = build_items(slots, vanilla_slots, huds, strings, textures)
    background = hi_background(vanilla_menu)

    files = {}  # путь в архиве -> байты
    changes = []

    def put_icons(folder, uid, facs_list):
        """Иконки ячейки: ваниль как есть, если там тот же предмет и размер; иначе генерируем."""
        size = slot_size(uid)
        icon_items = []
        for facs in facs_list:  # общая колонка: по одной картинке на класс (вариант ЕС)
            for it in slot_icons(facs, items)[:1 if len(facs_list) > 1 else 2]:
                if it not in icon_items:
                    icon_items.append(it)
        same_uid = {it.vanilla_uid for it in icon_items}
        if len(icon_items) == 1 and len(same_uid) == 1 and None not in same_uid and \
                slot_size(icon_items[0].vanilla_uid) == size:
            if folder == "unlocks" and icon_items[0].vanilla_uid == uid:
                return  # ванильные файлы и так на месте
            data = vanilla_files(vanilla_menu, icon_items[0].vanilla_uid)
        else:
            sources = []
            for it in icon_items:
                img = it.icon
                if img is None and it.vanilla_uid:  # нет текстуры — берём ванильную иконку
                    img = il.read_png(vanilla_menu.read(f"External/FlashMenu/images/unlocks/{it.vanilla_uid}.png"))
                sources.append(img)
            data = [il.write_png(img, alpha=n < 2) for n, img in enumerate(make_icons(sources, size, background))]
        for suffix, blob in zip((".png", "_locked.png", "_hi.png"), data):
            files[f"External/FlashMenu/images/{folder}/{uid}{suffix}"] = blob

    for (kit, uid), facs in sorted(slots.items()):
        names, descs = slot_texts(facs, items, strings)
        strings.set(f"NAME_HQ{kit}_UL_{uid}", names)
        strings.set(f"DESCRIPTION_HQ{kit}_UL_{uid}", descs)
        put_icons(f"unlock{kit}", uid, [facs])
        van = vanilla_slots.get((kit, uid), {})
        if not uid.startswith("5"):
            strings.set(f"NAME_UNLOCK_{uid}", names)
            strings.set(f"DESCRIPTION_UNLOCK_{uid}", descs)
            put_icons("unlocks", uid, [facs])
            if {t.lower() for t in van.values()} != {t.lower() for t in facs.values()}:
                changes.append(f"{uid}: {names['English']}")
    for uid in sorted({u for _, u in slots if u.startswith("5")}):
        names, descs = shared_texts(uid, slots, items, strings)
        strings.set(f"NAME_UNLOCK_{uid}", names)
        strings.set(f"DESCRIPTION_UNLOCK_{uid}", descs)
        put_icons("unlocks", uid, [slots[(kit, uid)] for kit in KITS])
        if names["English"] != strings.get(f"NAME_UNLOCK_{uid}")["English"] or len(
                {tuple(slots[(k, uid)].values()) for k in KITS}) > 1:
            changes.append(f"{uid}: {names['English']}")

    if preview_dir:
        write_preview(Path(preview_dir), files, strings, slots)
        return

    dfm = zipfile.ZipFile(REMASTER / "Objects" / "Menu_server.zip").read("External/FlashMenu/mainMenu.dfm")
    new_dfm, tabs, report = patch_menu(dfm)
    print("\n".join(report))
    write_zip(REMASTER / "Objects" / SERVER_ZIP, {"External/FlashMenu/mainMenu.dfm": new_dfm})
    write_zip(REMASTER / "Objects" / CLIENT_ZIP, files)
    if not original.exists():
        shutil.copy2(strings_path, original)
    strings_path.write_bytes(strings.dump())
    mount(REMASTER / "ServerArchives.con", f"Objects/{SERVER_ZIP}")
    mount(REMASTER / "ClientArchives.con", f"Objects/{CLIENT_ZIP}")
    print(f"картинок: {len(files)}, строк поощрений: {sum(1 for k in strings.rows if '_UL_' in k or 'UNLOCK_' in k)}")
    print("изменённые ячейки (общая страница / конец раунда):")
    print("  " + "\n  ".join(changes))


def write_zip(path, files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files):
            zf.writestr(name, files[name])
    path.write_bytes(buf.getvalue())
    print(f"записан {path.relative_to(GAME)} ({len(files)} файлов, {path.stat().st_size // 1024} КБ)")


MOUNT_TAG = "rem selfhost: HQ unlocks page for Project Remaster (Backend/tools/build_hq_patch.py)"


def mount(con, archive):
    text = con.read_text(encoding="latin-1")
    line = f"fileManager.mountArchive {archive} Menu"
    if line in text:
        return
    lines = text.split("\n")
    # после шапки-комментария Remaster, но до первого mountArchive
    at = next(i for i, l in enumerate(lines) if l.strip().lower().startswith("filemanager.mountarchive"))
    eol = "\r" if lines[0].endswith("\r") else ""
    lines[at:at] = [MOUNT_TAG + eol, line + eol]
    con.write_text("\n".join(lines), encoding="latin-1")
    print(f"подключён {archive} в {con.name}")


def uninstall():
    for con in ("ServerArchives.con", "ClientArchives.con"):
        path = REMASTER / con
        lines = path.read_text(encoding="latin-1").split("\n")
        keep = [l for l in lines if MOUNT_TAG not in l and "Menu_selfhost_hq_" not in l]
        if len(keep) != len(lines):
            path.write_text("\n".join(keep), encoding="latin-1")
            print("убрано из", con)
    for name in (SERVER_ZIP, CLIENT_ZIP):
        (REMASTER / "Objects" / name).unlink(missing_ok=True)
    original = REMASTER / "Localization" / STRINGS_BACKUP
    if original.exists():
        shutil.copy2(original, REMASTER / "Localization" / "strings.csv")
        original.unlink()
        print("strings.csv восстановлен")


def write_preview(out, files, strings, slots):
    """Лист-превью: для каждой вкладки — ячейки на ванильных подложках + названия в текст."""
    out.mkdir(parents=True, exist_ok=True)
    vanilla_menu = zipfile.ZipFile(VANILLA / "Menu_client.zip")

    def png(path):
        data = files.get(path)
        if data is None:
            try:
                data = vanilla_menu.read(path)
            except KeyError:
                return None
        return il.read_png(data)
    for folder in ["unlock1", "unlock2", "unlock3", "unlock4", "unlocks"]:
        uids = sorted({u for (k, u) in slots if folder == "unlocks" or f"unlock{k}" == folder})
        sheet = il.new(300 + 110 + 50 + 30, 100 * len(uids), (30, 30, 30, 255))
        for row, uid in enumerate(uids):
            base = f"External/FlashMenu/images/{folder}/{uid}"
            for x, suffix in ((0, "_hi.png"), (300, ".png"), (410, "_locked.png")):
                img = png(base + suffix)
                if img is None:
                    continue
                if suffix != "_hi.png":
                    bg = png(f"External/FlashMenu/images/unlocks/bg_{slot_size(uid)}_available.png")
                    if bg:
                        il.paste(sheet, bg, x, row * 100 + 4)
                il.paste(sheet, img, x, row * 100 + 4)
        (out / f"{folder}.png").write_bytes(il.write_png(sheet))
        with open(out / f"{folder}.txt", "w", encoding="utf-8") as f:
            for uid in uids:
                key = f"HQ{folder[-1]}_UL_" if folder != "unlocks" else "UNLOCK_"
                n, d = strings.get(f"NAME_{key}{uid}"), strings.get(f"DESCRIPTION_{key}{uid}")
                f.write(f"{uid}  {n['Russian']}  |  {n['English']}\n      {d['Russian']}\n")
    print("превью в", out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preview", metavar="DIR", help="только собрать превью картинок и строк")
    ap.add_argument("--uninstall", action="store_true", help="убрать патч и вернуть strings.csv")
    args = ap.parse_args()
    if args.uninstall:
        uninstall()
    else:
        build(args.preview)


if __name__ == "__main__":
    main()
