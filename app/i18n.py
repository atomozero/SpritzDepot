"""UI string translations.

Only the interface is translated; app names/descriptions stay in the author's
language (like Flathub, GitHub, etc.). Language is chosen by the `lang` cookie,
falling back to the browser's Accept-Language, then Italian.

Coverage note: the high-traffic pages (nav, home, app page, login, categories)
are fully translated. Admin and publish are technical, low-traffic forms and
are left for a later pass; they fall back to Italian via the default.
"""
from __future__ import annotations

LANGS = {
    "it": "Italiano",
    "es": "Español",
    "de": "Deutsch",
    "zh": "中文",
    "nl": "Nederlands",
    "fr": "Français",
    "ja": "日本語",
    "vec": "Vèneto",
}

# Flag emoji per language, for the picker. If WebPositive lacks the emoji font,
# the language name shown next to it keeps the picker usable. Venetian is a
# region, not a nation: a lion emoji evokes the Lion of St Mark.
FLAGS = {
    "it": "🇮🇹", "es": "🇪🇸", "de": "🇩🇪", "zh": "🇨🇳",
    "nl": "🇳🇱", "fr": "🇫🇷", "ja": "🇯🇵", "vec": "🦁",
}

DEFAULT_LANG = "it"

# Note on "vec" (Venetian): it has no single codified spelling and many local
# variants; the strings below are a reasonable common rendering, not an official
# standard. `normalize_lang` keeps 3-letter codes like "vec" intact.

# key -> {lang: text}. Missing (lang, key) falls back to Italian, then the key.
STRINGS: dict[str, dict[str, str]] = {
    'nav.search_placeholder': {"it": "Cerca un'app per Haiku", "es": 'Busca una app para Haiku', "de": 'Eine App für Haiku suchen', "zh": '搜索 Haiku 应用', "nl": 'Zoek een app voor Haiku', "fr": 'Rechercher une app pour Haiku', "ja": 'Haiku 用アプリを検索', "vec": "Serca un'app par Haiku"},
    'nav.search': {"it": 'Cerca', "es": 'Buscar', "de": 'Suchen', "zh": '搜索', "nl": 'Zoeken', "fr": 'Rechercher', "ja": '検索', "vec": 'Serca'},
    'nav.categories': {"it": 'Categorie', "es": 'Categorías', "de": 'Kategorien', "zh": '分类', "nl": 'Categorieën', "fr": 'Catégories', "ja": 'カテゴリ', "vec": 'Categorie'},
    'nav.my_apps': {"it": 'Le mie app', "es": 'Mis apps', "de": 'Meine Apps', "zh": '我的应用', "nl": 'Mijn apps', "fr": 'Mes apps', "ja": 'マイアプリ', "vec": 'Le me app'},
    'nav.publish': {"it": 'Pubblica', "es": 'Publicar', "de": 'Veröffentlichen', "zh": '发布', "nl": 'Publiceren', "fr": 'Publier', "ja": '公開', "vec": 'Publica'},
    'nav.admin': {"it": 'Admin', "es": 'Admin', "de": 'Admin', "zh": '管理', "nl": 'Beheer', "fr": 'Admin', "ja": '管理', "vec": 'Aministrasion'},
    'nav.login': {"it": 'Accedi', "es": 'Acceder', "de": 'Anmelden', "zh": '登录', "nl": 'Inloggen', "fr": 'Se connecter', "ja": 'ログイン', "vec": 'Entra'},
    'nav.logout': {"it": 'Esci', "es": 'Salir', "de": 'Abmelden', "zh": '退出', "nl": 'Uitloggen', "fr": 'Se déconnecter', "ja": 'ログアウト', "vec": 'Va fora'},
    'footer.text': {"it": "spritz e' un catalogo che punta agli autori originali. E' additivo a HaikuPorts, non un'alternativa: quando un'app esiste anche li', spritz te lo dice e ti manda alla versione curata.", "es": 'spritz es un catálogo que apunta a los autores originales. Es aditivo a HaikuPorts, no una alternativa: cuando una app también existe allí, spritz te lo dice y te lleva a la versión curada.', "de": 'spritz ist ein Katalog, der auf die ursprünglichen Autoren verweist. Es ergänzt HaikuPorts, ist keine Alternative: wenn eine App auch dort existiert, sagt spritz es dir und verweist auf die gepflegte Version.', "zh": 'spritz 是一个指向原始作者的目录。它是 HaikuPorts 的补充，而非替代：当某个应用也存在于那里时，spritz 会告诉你并引导你使用经过维护的版本。', "nl": 'spritz is een catalogus die naar de oorspronkelijke auteurs verwijst. Het is aanvullend op HaikuPorts, geen alternatief: als een app daar ook bestaat, vertelt spritz het je en verwijst naar de verzorgde versie.', "fr": "spritz est un catalogue qui pointe vers les auteurs originaux. Il complète HaikuPorts, ce n'est pas une alternative : quand une app existe aussi là-bas, spritz vous le dit et vous oriente vers la version maintenue.", "ja": 'spritz は元の作者を指すカタログです。HaikuPorts の代替ではなく補完であり、アプリがそちらにも存在する場合は spritz がそれを伝え、整備された版へ案内します。', "vec": 'spritz xe un catalogo che punta ai autori orixinali. Xe zonta a HaikuPorts, mìa na alternativa: cuando che na app esiste anca là, spritz te lo dixe e te manda a la version curà.'},
    'home.hero_title': {"it": 'Il catalogo del software per Haiku', "es": 'El catálogo de software para Haiku', "de": 'Der Software-Katalog für Haiku', "zh": 'Haiku 软件目录', "nl": 'De softwarecatalogus voor Haiku', "fr": 'Le catalogue de logiciels pour Haiku', "ja": 'Haiku 向けソフトウェアカタログ', "vec": 'El catalogo del software par Haiku'},
    'home.hero_lead': {"it": "Trova app native, sempre dagli autori originali. spritz raccoglie le fonti che esistono gia' (release su GitHub, repository di terze parti, archivi storici) in un unico indice cercabile.", "es": 'Encuentra apps nativas, siempre de los autores originales. spritz reúne las fuentes que ya existen (releases en GitHub, repositorios de terceros, archivos históricos) en un único índice buscable.', "de": 'Finde native Apps, immer von den ursprünglichen Autoren. spritz sammelt bereits vorhandene Quellen (GitHub-Releases, Drittanbieter-Repositorys, historische Archive) in einem durchsuchbaren Index.', "zh": '查找原生应用，始终来自原始作者。spritz 将已经存在的来源（GitHub 发布、第三方仓库、历史归档）汇集到一个可搜索的索引中。', "nl": 'Vind native apps, altijd van de oorspronkelijke auteurs. spritz verzamelt bestaande bronnen (GitHub-releases, repositories van derden, historische archieven) in één doorzoekbare index.', "fr": 'Trouvez des apps natives, toujours des auteurs originaux. spritz rassemble les sources qui existent déjà (releases GitHub, dépôts tiers, archives historiques) dans un index unique consultable.', "ja": '常に元の作者からのネイティブアプリを見つけましょう。spritz は既存のソース（GitHub のリリース、サードパーティのリポジトリ、歴史的アーカイブ）を検索可能な単一のインデックスにまとめます。', "vec": 'Cata app native, senpre dai autori orixinali. spritz raccoglie le fonti che esiste xà (release su GitHub, repository de tersi, archivi storici) in un sol indice serchàbile.'},
    'home.search_placeholder': {"it": 'Es. Genio, editor, IDE', "es": 'Ej. Genio, editor, IDE', "de": 'z.B. Genio, Editor, IDE', "zh": '例如 Genio、编辑器、IDE', "nl": 'Bijv. Genio, editor, IDE', "fr": 'Ex. Genio, éditeur, IDE', "ja": '例: Genio、エディタ、IDE', "vec": 'Es. Genio, editor, IDE'},
    'home.browse': {"it": 'Sfoglia', "es": 'Explorar', "de": 'Durchsuchen', "zh": '浏览', "nl": 'Bladeren', "fr": 'Parcourir', "ja": '閲覧', "vec": 'Sfoja'},
    'home.results_for': {"it": 'Risultati per', "es": 'Resultados para', "de": 'Ergebnisse für', "zh": '搜索结果：', "nl": 'Resultaten voor', "fr": 'Résultats pour', "ja": '検索結果:', "vec": 'Resultati par'},
    'home.browse_by_category': {"it": 'sfoglia per categoria', "es": 'explorar por categoría', "de": 'nach Kategorie durchsuchen', "zh": '按分类浏览', "nl": 'bladeren per categorie', "fr": 'parcourir par catégorie', "ja": 'カテゴリで閲覧', "vec": 'sfoja par categoria'},
    'home.clear_filters': {"it": 'azzera i filtri', "es": 'borrar filtros', "de": 'Filter zurücksetzen', "zh": '清除筛选', "nl": 'filters wissen', "fr": 'réinitialiser les filtres', "ja": 'フィルタを解除', "vec": 'neta i filtri'},
    'home.no_results': {"it": 'Nessun risultato. Prova con un altro termine.', "es": 'Sin resultados. Prueba con otro término.', "de": 'Keine Ergebnisse. Versuche einen anderen Begriff.', "zh": '没有结果。请尝试其他关键词。', "nl": 'Geen resultaten. Probeer een andere term.', "fr": 'Aucun résultat. Essayez un autre terme.', "ja": '結果がありません。別の語句をお試しください。', "vec": "Nissun resultà. Prova co 'n altro termine."},
    'home.empty_catalog': {"it": "Il catalogo e' ancora vuoto.", "es": 'El catálogo aún está vacío.', "de": 'Der Katalog ist noch leer.', "zh": '目录还是空的。', "nl": 'De catalogus is nog leeg.', "fr": 'Le catalogue est encore vide.', "ja": 'カタログはまだ空です。', "vec": 'El catalogo xe ancora vodo.'},
    'home.prev': {"it": 'Precedente', "es": 'Anterior', "de": 'Zurück', "zh": '上一页', "nl": 'Vorige', "fr": 'Précédent', "ja": '前へ', "vec": 'Indrìo'},
    'home.next': {"it": 'Successiva', "es": 'Siguiente', "de": 'Weiter', "zh": '下一页', "nl": 'Volgende', "fr": 'Suivant', "ja": '次へ', "vec": 'Vanti'},
    'home.page_of': {"it": 'Pagina {p} di {n}', "es": 'Página {p} de {n}', "de": 'Seite {p} von {n}', "zh": '第 {p} 页，共 {n} 页', "nl": 'Pagina {p} van {n}', "fr": 'Page {p} sur {n}', "ja": '{n} ページ中 {p} ページ', "vec": 'Pagina {p} de {n}'},
    'home.apps_count': {"it": '{n} app', "es": '{n} apps', "de": '{n} Apps', "zh": '{n} 个应用', "nl": '{n} apps', "fr": '{n} apps', "ja": '{n} 個のアプリ', "vec": '{n} app'},
    'badge.also_on_hp': {"it": 'anche su HaikuPorts', "es": 'también en HaikuPorts', "de": 'auch in HaikuPorts', "zh": '也在 HaikuPorts 中', "nl": 'ook op HaikuPorts', "fr": 'aussi sur HaikuPorts', "ja": 'HaikuPorts にもあり', "vec": 'anca su HaikuPorts'},
    'cat.browse_title': {"it": 'Sfoglia per categoria', "es": 'Explorar por categoría', "de": 'Nach Kategorie durchsuchen', "zh": '按分类浏览', "nl": 'Bladeren per categorie', "fr": 'Parcourir par catégorie', "ja": 'カテゴリで閲覧', "vec": 'Sfoja par categoria'},
    'cat.back': {"it": 'torna al catalogo', "es": 'volver al catálogo', "de": 'zurück zum Katalog', "zh": '返回目录', "nl": 'terug naar de catalogus', "fr": 'retour au catalogue', "ja": 'カタログに戻る', "vec": 'torna al catalogo'},
    'cat.empty': {"it": 'Nessuna categoria ancora.', "es": 'Aún no hay categorías.', "de": 'Noch keine Kategorien.', "zh": '暂无分类。', "nl": 'Nog geen categorieën.', "fr": 'Aucune catégorie pour le moment.', "ja": 'カテゴリはまだありません。', "vec": 'Ancora nissuna categoria.'},
    'app.install': {"it": 'Installa', "es": 'Instalar', "de": 'Installieren', "zh": '安装', "nl": 'Installeren', "fr": 'Installer', "ja": 'インストール', "vec": 'Instala'},
    'app.channel': {"it": 'Canale', "es": 'Canal', "de": 'Kanal', "zh": '渠道', "nl": 'Kanaal', "fr": 'Canal', "ja": 'チャンネル', "vec": 'Canal'},
    'app.author': {"it": 'Autore', "es": 'Autor', "de": 'Autor', "zh": '作者', "nl": 'Auteur', "fr": 'Auteur', "ja": '作者', "vec": 'Autor'},
    'app.packager': {"it": 'Packager', "es": 'Empaquetador', "de": 'Packager', "zh": '打包者', "nl": 'Packager', "fr": 'Empaqueteur', "ja": 'パッケージャ', "vec": 'Inpachetador'},
    'app.site': {"it": 'Sito', "es": 'Sitio', "de": 'Webseite', "zh": '网站', "nl": 'Site', "fr": 'Site', "ja": 'サイト', "vec": 'Sito'},
    'app.license': {"it": 'Licenza', "es": 'Licencia', "de": 'Lizenz', "zh": '许可证', "nl": 'Licentie', "fr": 'Licence', "ja": 'ライセンス', "vec": 'Licensa'},
    'app.screenshots': {"it": 'Schermate', "es": 'Capturas', "de": 'Screenshots', "zh": '截图', "nl": 'Schermafbeeldingen', "fr": "Captures d'écran", "ja": 'スクリーンショット', "vec": 'Schermade'},
    'app.also_on_hp_title': {"it": 'Anche su HaikuPorts.', "es": 'También en HaikuPorts.', "de": 'Auch in HaikuPorts.', "zh": '也在 HaikuPorts 中。', "nl": 'Ook op HaikuPorts.', "fr": 'Aussi sur HaikuPorts.', "ja": 'HaikuPorts にもあります。', "vec": 'Anca su HaikuPorts.'},
    'app.add_repo': {"it": 'Aggiungi il repository in HaikuDepot', "es": 'Añade el repositorio en HaikuDepot', "de": 'Repository in HaikuDepot hinzufügen', "zh": '在 HaikuDepot 中添加该仓库', "nl": 'Voeg de repository toe in HaikuDepot', "fr": 'Ajouter le dépôt dans HaikuDepot', "ja": 'HaikuDepot にリポジトリを追加', "vec": 'Zonta el repository in HaikuDepot'},
    'app.from_haikuports': {"it": "Questa app e' curata in HaikuPorts. Installala da li', e' gia' disponibile in HaikuDepot.", "es": 'Esta app está curada en HaikuPorts. Instálala desde allí, ya está disponible en HaikuDepot.', "de": 'Diese App wird in HaikuPorts gepflegt. Installiere sie von dort, sie ist bereits in HaikuDepot verfügbar.', "zh": '此应用在 HaikuPorts 中维护。请从那里安装，它已在 HaikuDepot 中提供。', "nl": 'Deze app wordt onderhouden in HaikuPorts. Installeer hem daar, hij is al beschikbaar in HaikuDepot.', "fr": 'Cette app est maintenue dans HaikuPorts. Installez-la depuis là, elle est déjà disponible dans HaikuDepot.', "ja": 'このアプリは HaikuPorts で管理されています。そちらからインストールしてください。HaikuDepot で既に利用できます。', "vec": 'Sta app xe curà su HaikuPorts. Instalela da là, xe xà disponìbile in HaikuDepot.'},
    'login.title': {"it": 'Accedi', "es": 'Acceder', "de": 'Anmelden', "zh": '登录', "nl": 'Inloggen', "fr": 'Se connecter', "ja": 'ログイン', "vec": 'Entra'},
    'login.lead': {"it": 'Entra per gestire la tua libreria e pubblicare le tue app. Se non hai un account, registrane uno: basta una email e una password.', "es": 'Entra para gestionar tu biblioteca y publicar tus apps. Si no tienes cuenta, crea una: basta un email y una contraseña.', "de": 'Melde dich an, um deine Bibliothek zu verwalten und deine Apps zu veröffentlichen. Ohne Konto registriere eines: nur E-Mail und Passwort nötig.', "zh": '登录以管理你的库并发布你的应用。如果没有账户，注册一个即可：只需邮箱和密码。', "nl": 'Log in om je bibliotheek te beheren en je apps te publiceren. Geen account? Maak er een aan: alleen e-mail en wachtwoord nodig.', "fr": 'Connectez-vous pour gérer votre bibliothèque et publier vos apps. Sans compte, créez-en un : un email et un mot de passe suffisent.', "ja": 'ログインしてライブラリを管理し、アプリを公開しましょう。アカウントがなければ登録してください。メールとパスワードだけで済みます。', "vec": 'Entra par gestir la to libraria e publicar le to app. Se no ti ga un account, registrane uno: basta na email e na password.'},
    'login.email': {"it": 'Email', "es": 'Email', "de": 'E-Mail', "zh": '邮箱', "nl": 'E-mail', "fr": 'Email', "ja": 'メール', "vec": 'Email'},
    'login.password': {"it": 'Password', "es": 'Contraseña', "de": 'Passwort', "zh": '密码', "nl": 'Wachtwoord', "fr": 'Mot de passe', "ja": 'パスワード', "vec": 'Password'},
    'login.min_chars': {"it": 'Almeno 8 caratteri.', "es": 'Al menos 8 caracteres.', "de": 'Mindestens 8 Zeichen.', "zh": '至少 8 个字符。', "nl": 'Minstens 8 tekens.', "fr": 'Au moins 8 caractères.', "ja": '8 文字以上。', "vec": 'Almanco 8 caràteri.'},
    'login.register': {"it": 'Registrati', "es": 'Registrarse', "de": 'Registrieren', "zh": '注册', "nl": 'Registreren', "fr": "S'inscrire", "ja": '登録', "vec": 'Registrate'},
    'lang.label': {"it": 'Lingua', "es": 'Idioma', "de": 'Sprache', "zh": '语言', "nl": 'Taal', "fr": 'Langue', "ja": '言語', "vec": 'Lengua'},
}


def normalize_lang(value: str | None) -> str:
    """Map an arbitrary value (cookie or Accept-Language) to a supported code.

    Handles both 2-letter codes (it, de, ja) and longer ones (vec). Tries the
    full token first, then its 2-letter prefix (so "it-IT" -> "it")."""
    if not value:
        return DEFAULT_LANG
    code = value.strip().lower()
    # drop a region/quality suffix like "it-IT" or "en;q=0.8" for the prefix try
    base = code.split("-")[0].split(";")[0]
    if code in LANGS:
        return code
    if base in LANGS:
        return base
    return DEFAULT_LANG


def t(key: str, lang: str = DEFAULT_LANG, **fmt) -> str:
    """Translate `key` into `lang`, falling back to Italian then the key itself.
    Supports {placeholder} formatting via kwargs."""
    entry = STRINGS.get(key)
    if not entry:
        return key
    text = entry.get(lang) or entry.get(DEFAULT_LANG) or key
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError):
            return text
    return text
