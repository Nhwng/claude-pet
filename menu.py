"""The right-click menu: a small bar (swap this pet, ⚙ settings) and the settings panel behind the gear."""
import threading
import time

from look import CHECK_BOX, CHIP_LINE, DICE, FONT_TAG, FONT_TITLE, GEAR, ICON_COLORS, INK, MUTED, PAPER, TEXT, WAIT_INK
from pet import STARTUP_LINK, shortcut, write_config
from sprites import ICONS, packs, tr


class MenuMixin:
    """Mixed into PetApp: uses its canvas, card(), pixels(), card_x(), pet_at(), cats, pack and settings."""

    def measure(self, text, font):
        import tkinter.font
        f = self.fonts.setdefault(font, tkinter.font.Font(root=self.root, font=font))
        return f.measure(text), f.metrics('linespace')

    def open_menu(self, x, y):
        """Right-click a pet: swap it for another one, or open the ⚙ settings."""
        text, lang = TEXT[self.settings['lang']], self.settings['lang']
        self.menu_sid, self.menu_x = self.pet_at(x, y), x
        cat, row = self.cats.get(self.menu_sid), []
        if cat and self.next_kind(cat) != cat.kind:
            row.append(('swap', text['swap'].format(pet=tr(self.pack['pets'][self.next_kind(cat)]['label'], lang)),
                        'dice', False))
        row.append(('settings', text['settings'], 'gear', False))
        self.show_bar([row])

    def open_settings(self):
        """⚙: which pack, which screen, bigger pets, sound, start with Windows, language, quit."""
        lang = self.settings['lang']
        text = TEXT[lang]
        rows = [[(f'pack:{key}', tr(pack['name'], lang), pack['pets'][0], key == self.settings['pack'])
                 for key, pack in packs().items()]]
        labels = [text['pets']]
        monitors = self.monitors()
        if len(monitors) > 1:
            names = [text['screen_main']] + ([text['screen_second']] if len(monitors) == 2 else
                                             [text['screen_n'].format(n=n) for n in range(2, len(monitors) + 1)])
            keys = ['main' if m['primary'] else m['device'] for m in monitors]
            rows.append([(f'screen:{key}', name, None, key == self.settings['screen']) for key, name in zip(keys, names)]
                        + [('screen:auto', text['screen_auto'], None, self.settings['screen'] == 'auto')])
            labels.append(text['screen'])
        rows.append([('big', text['big'], 'check', self.settings['big']),
                     ('sound', text['sound'], 'check', self.settings['sound']),
                     ('autostart', text['autostart'], 'check', STARTUP_LINK.exists()),
                     ('lang', text['other_lang'], None, False), ('quit', text['quit'], None, False)])
        self.show_bar(rows, labels)

    def show_bar(self, rows, labels=()):
        """Lay rows of chips out on one card at the top of the strip, each after its label (if any),
        with ✕ closing it on the first row."""
        self.close_menu()
        s = self.ui
        sizes = [[self.chip_size(text, icon) for _, text, icon, _ in row] for row in rows]
        label_w = max((self.measure(label, FONT_TAG)[0] + 3 * s for label in labels if label), default=0)
        close_w = self.measure('✕', FONT_TITLE)[0]
        row_h = [max(h for _, h in row) for row in sizes]
        widths = [label_w + sum(w + 2 * s for w, _ in row) for row in sizes]
        width = 4 * s + max([widths[0] + close_w + 2 * s, *widths[1:]]) + 4 * s
        height = 3 * s + sum(row_h) + 2 * s * (len(rows) - 1) + 3 * s
        x0, y0 = self.card_x(self.menu_x, width), 2 * s
        self.canvas.create_image(x0, y0, image=self.card(width, height, INK), anchor='nw', tags=('menu',))
        hits, top = [], y0 + 3 * s
        for i, (row, row_sizes) in enumerate(zip(rows, sizes)):
            mid, cx = top + row_h[i] // 2, x0 + 4 * s + label_w
            if i < len(labels) and labels[i]:
                self.canvas.create_text(x0 + 4 * s, mid, text=labels[i], font=FONT_TAG, fill=MUTED, anchor='w',
                                        tags=('menu',))
            for (action, text, icon, on), (w, h) in zip(row, row_sizes):
                self.chip(cx, mid - h // 2, w, h, text, icon, on, action == 'quit')
                hits.append((cx, mid - h // 2, cx + w, mid + h // 2, action))
                cx += w + 2 * s
            top += row_h[i] + 2 * s
        close_x = x0 + width - 4 * s - close_w
        self.canvas.create_text(close_x, y0 + 3 * s + row_h[0] // 2, text='✕', font=FONT_TITLE, fill=MUTED, anchor='w',
                                tags=('menu',))
        hits.append((close_x - 2 * s, y0, x0 + width, y0 + 3 * s + row_h[0], 'close'))
        self.menu_hits, self.menu_box = hits, (x0, y0, x0 + width, y0 + height)
        self.menu_until = time.monotonic() + 6

    def chip_size(self, text, icon):
        s, (w, h) = self.ui, self.measure(text, FONT_TAG)
        iw, ih = self.chip_icon(icon)[2:] if icon else (0, 0)
        return 3 * s + iw + (2 * s if icon else 0) + w + 3 * s, max(h, ih) + 2 * s

    def chip_icon(self, icon):
        """(rows, colors, width, height) of a chip's little picture: a pet's face, a checkbox, dice or the gear."""
        if isinstance(icon, str):
            art = {'check': (CHECK_BOX, ICON_COLORS['box']), 'dice': (DICE, ICON_COLORS['dice']),
                   'gear': (GEAR, ICON_COLORS['gear'])}[icon]
            return (*art, 7 * self.ui, 7 * self.ui)
        px = self.dpi * (2 if len(icon['icon'][0]) < 10 else 1)
        return icon['icon'], icon['colors'], len(icon['icon'][0]) * px, len(icon['icon']) * px

    def chip(self, x, y, w, h, text, icon, on, danger):
        """One button; the chosen one is filled in, and a ticked checkbox turns into a green tick."""
        s = self.ui
        self.canvas.create_image(x, y, image=self.card(w, h, INK if on else CHIP_LINE, paper=INK if on else PAPER),
                                 anchor='nw', tags=('menu',))
        tx = x + 3 * s
        if icon:
            rows, colors, iw, ih = self.chip_icon(icon)
            if icon == 'check' and on:
                rows, colors = ICONS['done'], ICON_COLORS['done']
            self.pixels(tx, y + (h - ih) // 2, rows, colors, iw // len(rows[0]), tags=('menu',))
            tx += iw + 2 * s
        color = PAPER if on else WAIT_INK if danger else INK
        self.canvas.create_text(tx, y + h // 2, text=text, font=FONT_TAG, fill=color, anchor='w', tags=('menu',))

    def next_kind(self, cat):
        """The next pet in the pack that nobody else on the strip is, else simply the next one."""
        n, used = len(self.pack['pets']), {c.kind for c in self.cats.values() if c is not cat}
        order = [(cat.kind + i) % n for i in range(1, n)]
        return next((k for k in order if k not in used), order[0] if order else cat.kind)

    def swap(self, cat):
        cat.kind = self.next_kind(cat)
        cat.x = min(cat.x, self.w - self.width(cat.kind))
        cat.fx, cat.move_t, cat.shown = [], None, None  # new sprite, new plate (its icon), no stale shots
        self.remember(self.project(cat.rec), cat.kind)      # and the project keeps it

    def close_menu(self):
        self.canvas.delete('menu')
        self.menu_hits = None

    def on_motion(self, event):
        x0, y0, x1, y1 = self.menu_box
        if self.menu_hits is not None and x0 <= event.x <= x1 and y0 <= event.y <= y1:
            self.menu_until = time.monotonic() + 6  # stays open while the mouse is over it

    def menu_press(self, event):
        """A left click while the menu is open: True when the menu took it."""
        if self.menu_hits is None:
            return False
        x0, y0, x1, y1 = self.menu_box
        if not (x0 <= event.x <= x1 and y0 <= event.y <= y1):
            self.close_menu()  # clicked elsewhere: close, and let the click do its usual thing
            return False
        action = next((a for ax0, ay0, ax1, ay1, a in self.menu_hits
                       if ax0 <= event.x <= ax1 and ay0 <= event.y <= ay1), None)
        if action:
            self.menu_action(action)
        return True

    def menu_action(self, action):
        if action == 'settings':
            return self.open_settings()
        self.close_menu()
        if action == 'quit':
            self.root.destroy()
        elif action in ('big', 'sound'):
            write_config(**{action: not self.settings[action]})
        elif action == 'lang':
            write_config(lang='vi' if self.settings['lang'] == 'en' else 'en')
        elif action == 'swap' and self.menu_sid in self.cats:
            self.swap(self.cats[self.menu_sid])
        elif action.startswith('pack:'):
            write_config(pack=action[5:])
        elif action.startswith('screen:'):
            write_config(screen=action[7:])
        elif action == 'autostart':  # PowerShell makes the shortcut in about a second: don't freeze the pets for it
            threading.Thread(target=shortcut, args=(STARTUP_LINK.exists(), STARTUP_LINK), daemon=True).start()
