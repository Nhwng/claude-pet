"""How the pet looks and talks: colours, fonts, small icons, and every line it says in each language."""

TEXT = {
    'en': {'done': '{name} is done!', 'ask_q': '{name} has a question', 'ask_plan': '{name} wants the plan approved',
           'ask_tool': '{name} wants to use {tool}', 'ask_any': '{name} needs a decision', 'click': 'click {pet} to open it',
           'pets': 'Pets', 'swap': 'Swap to {pet}', 'settings': 'Settings', 'big': 'Bigger pets', 'sound': 'Sound',
           'quit': 'Quit', 'other_lang': 'Tiếng Việt', 'autostart': 'Start with Windows', 'screen': 'Screen',
           'screen_main': 'Main screen', 'screen_second': 'Second screen', 'screen_n': 'Screen {n}',
           'screen_auto': 'Follow my window', 'mode': 'Mode', 'mode_chill': 'Chill', 'mode_game': 'Game',
           'levelup': 'LEVEL UP!', 'written': 'Claude has written {n} tokens', 'counting': 'Counting tokens…',
           'to_next': '{n} tokens to Lv {level}', 'top': 'Top level!', 'beaten': '{bosses} bosses · {bugs} bugs beaten'},
    'vi': {'done': '{name} xong rồi!', 'ask_q': '{name} cần bạn trả lời câu hỏi', 'ask_plan': '{name} cần bạn duyệt plan',
           'ask_tool': '{name} cần bạn duyệt {tool}', 'ask_any': '{name} cần bạn quyết định', 'click': 'bấm vào {pet} để mở',
           'pets': 'Bộ pet', 'swap': 'Đổi sang {pet}', 'settings': 'Cài đặt', 'big': 'Pet to hơn', 'sound': 'Âm thanh',
           'quit': 'Thoát', 'other_lang': 'English', 'autostart': 'Tự chạy khi bật máy', 'screen': 'Màn hình',
           'screen_main': 'Màn hình chính', 'screen_second': 'Màn hình phụ', 'screen_n': 'Màn hình {n}',
           'screen_auto': 'Tự động', 'mode': 'Chế độ', 'mode_chill': 'Chill', 'mode_game': 'Game',
           'levelup': 'LÊN CẤP!', 'written': 'Claude đã viết {n} token', 'counting': 'Đang đếm token…',
           'to_next': 'Còn {n} token lên Lv {level}', 'top': 'Cấp tối đa!', 'beaten': 'Đã hạ {bosses} boss · {bugs} bug'},
}

INK, MUTED, PAPER, SHADOW = '#2a2230', '#8a7f8c', '#fffdf7', '#1d1822'
CHIP_LINE, WAIT_INK = '#cfc8d6', '#d6453d'
XP_COLOR = '#ffb020'                                        # the experience bar and the "LEVEL UP!" card
TIER_COLORS = (None, '#c27a3c', '#aeb8c8', '#f2c230')       # plate rims: bronze Lv 10, silver Lv 25, gold Lv 50
ALARM_COLORS = {'done': '#2f9e5b', 'waiting': '#e5484d'}
FX_COLORS = {'z': '#6d7fa6', 'g': '#ffffff', 'y': '#ffd84a', 'w': '#ffffff'}
FONT_TITLE, FONT_SUB, FONT_TAG = ('Segoe UI', 10, 'bold'), ('Segoe UI', 8), ('Segoe UI', 8, 'bold')

# 7x7 icons; each colour dict must stay the same object (images are cached by it)
CHECK_BOX = ['ccccccc', 'c.....c', 'c.....c', 'c.....c', 'c.....c', 'c.....c', 'ccccccc']
DICE = ['.ccccc.', 'cpppppc', 'cpdpdpc', 'cpppppc', 'cpdpdpc', 'cpppppc', '.ccccc.']
GEAR = ['..c.c..', '.ccccc.', 'cc...cc', '.c...c.', 'cc...cc', '.ccccc.', '..c.c..']
CLASS_ICONS = {  # a hero's name plate: what it fights with
    'slash': ['......w', '.....wc', '....wc.', 'k..wc..', '.kwc...', '.kk....', 'k..k...'],
    'punch': ['.......', '.cccc..', 'cwwwwc.', 'cwwwwc.', 'cwwwwc.', '.cccc..', '.......'],
    'spell': ['...w...', '..wkw..', '...w...', '...c...', '...c...', '...c...', '...c...'],
    'arrow': ['.c.....', 'c.c..w.', 'c..cwk.', 'c...k..', 'c..cwk.', 'c.c..w.', '.c.....'],
}
CLASS_ICON_COLORS = {'c': '#7a4a24', 'w': '#e9eef7', 'k': '#f2c230'}
ICON_COLORS = {**{kind: {'c': c, 'w': '#ffffff'} for kind, c in ALARM_COLORS.items()},
               'box': {'c': MUTED}, 'dice': {'c': INK, 'p': '#ffffff', 'd': INK}, 'gear': {'c': INK}}
