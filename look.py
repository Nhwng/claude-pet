"""How the pet looks and talks: colours, fonts, small icons, and every line it says in each language."""

TEXT = {
    'en': {'done': '{name} is done!', 'ask_q': '{name} has a question', 'ask_plan': '{name} wants the plan approved',
           'ask_tool': '{name} wants to use {tool}', 'ask_any': '{name} needs a decision', 'click': 'click {pet} to open it',
           'pets': 'Pets', 'swap': 'Swap to {pet}', 'settings': 'Settings', 'big': 'Bigger pets', 'sound': 'Sound',
           'quit': 'Quit', 'other_lang': 'Tiếng Việt', 'autostart': 'Start with Windows', 'screen': 'Screen',
           'screen_main': 'Main screen', 'screen_second': 'Second screen', 'screen_n': 'Screen {n}',
           'screen_auto': 'Follow my window'},
    'vi': {'done': '{name} xong rồi!', 'ask_q': '{name} cần bạn trả lời câu hỏi', 'ask_plan': '{name} cần bạn duyệt plan',
           'ask_tool': '{name} cần bạn duyệt {tool}', 'ask_any': '{name} cần bạn quyết định', 'click': 'bấm vào {pet} để mở',
           'pets': 'Bộ pet', 'swap': 'Đổi sang {pet}', 'settings': 'Cài đặt', 'big': 'Pet to hơn', 'sound': 'Âm thanh',
           'quit': 'Thoát', 'other_lang': 'English', 'autostart': 'Tự chạy khi bật máy', 'screen': 'Màn hình',
           'screen_main': 'Màn hình chính', 'screen_second': 'Màn hình phụ', 'screen_n': 'Màn hình {n}',
           'screen_auto': 'Tự động'},
}

INK, MUTED, PAPER, SHADOW = '#2a2230', '#8a7f8c', '#fffdf7', '#1d1822'
CHIP_LINE, WAIT_INK = '#cfc8d6', '#d6453d'
ALARM_COLORS = {'done': '#2f9e5b', 'waiting': '#e5484d'}
FX_COLORS = {'z': '#6d7fa6', 'g': '#ffffff', 'y': '#ffd84a', 'w': '#ffffff'}
FONT_TITLE, FONT_SUB, FONT_TAG = ('Segoe UI', 10, 'bold'), ('Segoe UI', 8), ('Segoe UI', 8, 'bold')

# 7x7 icons; each colour dict must stay the same object (images are cached by it)
CHECK_BOX = ['ccccccc', 'c.....c', 'c.....c', 'c.....c', 'c.....c', 'c.....c', 'ccccccc']
DICE = ['.ccccc.', 'cpppppc', 'cpdpdpc', 'cpppppc', 'cpdpdpc', 'cpppppc', '.ccccc.']
GEAR = ['..c.c..', '.ccccc.', 'cc...cc', '.c...c.', 'cc...cc', '.ccccc.', '..c.c..']
ICON_COLORS = {**{kind: {'c': c, 'w': '#ffffff'} for kind, c in ALARM_COLORS.items()},
               'box': {'c': MUTED}, 'dice': {'c': INK, 'p': '#ffffff', 'd': INK}, 'gear': {'c': INK}}
