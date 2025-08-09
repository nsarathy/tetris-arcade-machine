# tetris.py
# author: nsarathy

import os
import random
import hashlib
import secrets
import datetime
import tkinter as tk
from tkinter import simpledialog, messagebox, ttk

# ===== Coffy imports =====
from coffy.sql import init as sql_init, close as sql_close, Model, Integer, Text
from coffy.nosql import db as nosql_db

# ===== Storage setup =====
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

SQLITE_PATH = os.path.join(DATA_DIR, "tetris.sqlite")
USERS_JSON = os.path.join(DATA_DIR, "users.json")

sql_init(SQLITE_PATH)


# ORM table for game history
class Game(Model):
    id = Integer(primary_key=True, nullable=False)
    name = Text(nullable=False)
    score = Integer()
    lines = Integer()
    level = Integer()
    played_at = Text(nullable=False)


Game.objects.create_table()

# NoSQL collection for users
users = nosql_db("users", path=USERS_JSON)


# ===== Auth helpers (NoSQL) =====
def _hash_pw(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def find_user(name: str):
    rec = users.where("name").eq(name).first()
    return rec


def create_user(name: str, password: str):
    if not password:
        raise ValueError("Password required")
    salt = secrets.token_hex(8)
    users.add(
        {
            "name": name,
            "salt": salt,
            "hash": _hash_pw(password, salt),
            "created": datetime.datetime.utcnow().isoformat() + "Z",
        }
    )


def verify_user(name: str, password: str) -> bool:
    rec = find_user(name)
    if not rec:
        return False
    expect = rec.get("hash")
    salt = rec.get("salt", "")
    return _hash_pw(password, salt) == expect


def prompt_for_name(root) -> str | None:
    return simpledialog.askstring("Player", "Enter player name:", parent=root)


def prompt_for_password(root, prompt="Enter password:") -> str | None:
    d = tk.Toplevel(root)
    d.title("Password")
    d.transient(root)
    d.grab_set()
    tk.Label(d, text=prompt).grid(row=0, column=0, padx=10, pady=10)
    e = tk.Entry(d, show="*")
    e.grid(row=1, column=0, padx=10)
    e.focus_set()
    out = {"pw": None}

    def ok():
        out["pw"] = e.get()
        d.destroy()

    def cancel():
        out["pw"] = None
        d.destroy()

    tk.Frame(d).grid(row=2, column=0, pady=8)
    tk.Button(d, text="OK", command=ok).grid(
        row=3, column=0, sticky="w", padx=10, pady=10
    )
    tk.Button(d, text="Cancel", command=cancel).grid(
        row=3, column=0, sticky="e", padx=10, pady=10
    )
    d.wait_window()
    return out["pw"]


def login_flow(root) -> str | None:
    while True:
        name = prompt_for_name(root)
        if not name:
            return None
        rec = find_user(name)
        if rec:
            pw = prompt_for_password(root, "Password for existing player:")
            if pw is None:
                # allow choose different name
                if messagebox.askyesno("Change name", "Choose a different name?"):
                    continue
                return None
            if verify_user(name, pw):
                return name
            messagebox.showerror("Auth failed", "Wrong password")
            # loop to allow try again or different name
            continue
        else:
            # new user, set password
            pw1 = prompt_for_password(root, "Set a password:")
            if pw1 is None:
                if messagebox.askyesno("Change name", "Choose a different name?"):
                    continue
                return None
            pw2 = prompt_for_password(root, "Confirm password:")
            if pw2 is None or pw1 != pw2:
                messagebox.showerror("Mismatch", "Passwords do not match")
                continue
            try:
                create_user(name, pw1)
                messagebox.showinfo("Welcome", f"Player created: {name}")
                return name
            except Exception as e:
                messagebox.showerror("Error", str(e))
                continue


# ===== Tetris game =====
COLS, ROWS = 10, 20
CELL = 30
W, H = COLS * CELL, ROWS * CELL
START_DELAY = 500
LEVEL_STEP = 40
LINES_PER_LEVEL = 10

SHAPES = {
    "I": [[(0, 1), (1, 1), (2, 1), (3, 1)], [(2, 0), (2, 1), (2, 2), (2, 3)]],
    "J": [
        [(0, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (2, 2)],
        [(1, 0), (1, 1), (0, 2), (1, 2)],
    ],
    "L": [
        [(2, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (1, 2), (2, 2)],
        [(0, 1), (1, 1), (2, 1), (0, 2)],
        [(0, 0), (1, 0), (1, 1), (1, 2)],
    ],
    "O": [[(1, 0), (2, 0), (1, 1), (2, 1)]],
    "S": [[(1, 0), (2, 0), (0, 1), (1, 1)], [(1, 0), (1, 1), (2, 1), (2, 2)]],
    "T": [
        [(1, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (2, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (1, 2)],
        [(1, 0), (0, 1), (1, 1), (1, 2)],
    ],
    "Z": [[(0, 0), (1, 0), (1, 1), (2, 1)], [(2, 0), (1, 1), (2, 1), (1, 2)]],
}
COLORS = {
    "I": "#53d1f5",
    "J": "#5a79ff",
    "L": "#ff9f40",
    "O": "#ffd93b",
    "S": "#7dd36a",
    "T": "#ba6bff",
    "Z": "#ff6b6b",
    "G": "#445",
}


class Piece:
    def __init__(self, kind):
        self.kind = kind
        self.rot = 0
        self.x = 3
        self.y = 0

    @property
    def blocks(self):
        return SHAPES[self.kind][self.rot]

    def rotated(self):
        p = Piece(self.kind)
        p.rot = (self.rot + 1) % len(SHAPES[self.kind])
        p.x, p.y = self.x, self.y
        return p

    def moved(self, dx, dy):
        p = Piece(self.kind)
        p.rot = self.rot
        p.x, p.y = self.x + dx, self.y + dy
        return p


class Tetris:
    def __init__(self, root):
        self.root = root
        root.title("Tk Tetris + Coffy")

        # Top bar
        top = tk.Frame(root, bg="#111")
        top.pack(fill="x")
        self.lbl_player = tk.Label(
            top, text="Player: -", fg="#eee", bg="#111", font=("Consolas", 12)
        )
        self.lbl_player.pack(side="left", padx=8, pady=6)
        tk.Button(top, text="Change player", command=self.change_player).pack(
            side="left", padx=6
        )
        tk.Button(top, text="Leaderboard", command=self.show_leaderboard).pack(
            side="left", padx=6
        )

        # Canvas and info
        self.canvas = tk.Canvas(
            root, width=W, height=H, bg="#111", highlightthickness=0
        )
        self.canvas.pack(padx=8, pady=8)
        self.info = tk.Label(root, font=("Consolas", 12), fg="#eee", bg="#111")
        self.info.pack()

        self.help = tk.Label(
            root,
            font=("Consolas", 10),
            fg="#ccc",
            bg="#111",
            text="← → move, ↑ rotate, ↓ soft drop, Space hard drop, P pause, R restart",
        )
        self.help.pack(pady=(0, 8))

        self.player_name = None
        self.reset()
        self.bind_keys()
        self.login_and_start()
        self.tick()

    def login_and_start(self):
        name = login_flow(self.root)
        if not name:
            self.root.destroy()
            return
        self.player_name = name
        self.lbl_player.config(text=f"Player: {self.player_name}")

    def change_player(self):
        name = login_flow(self.root)
        if name:
            self.player_name = name
            self.lbl_player.config(text=f"Player: {self.player_name}")

    def reset(self):
        self.board = [[None for _ in range(COLS)] for _ in range(ROWS)]
        self.cur = self.new_piece()
        self.next = self.new_piece()
        self.score = 0
        self.lines = 0
        self.level = 1
        self.delay = START_DELAY
        self.paused = False
        self.game_over = False

    def new_piece(self):
        return Piece(random.choice(list(SHAPES.keys())))

    def bind_keys(self):
        r = self.root
        r.bind("<Left>", lambda e: self.move(-1, 0))
        r.bind("<Right>", lambda e: self.move(1, 0))
        r.bind("<Down>", lambda e: self.soft_drop())
        r.bind("<Up>", lambda e: self.rotate())
        r.bind("<space>", lambda e: self.hard_drop())
        r.bind("p", lambda e: self.toggle_pause())
        r.bind("P", lambda e: self.toggle_pause())
        r.bind("r", lambda e: self.restart())
        r.bind("R", lambda e: self.restart())

    def toggle_pause(self):
        if self.game_over:
            return
        self.paused = not self.paused
        self.draw()

    def restart(self):
        self.reset()
        self.draw()

    def valid(self, piece):
        for bx, by in piece.blocks:
            x = piece.x + bx
            y = piece.y + by
            if x < 0 or x >= COLS or y < 0 or y >= ROWS:
                return False
            if self.board[y][x]:
                return False
        return True

    def lock(self):
        color = COLORS[self.cur.kind]
        for bx, by in self.cur.blocks:
            x = self.cur.x + bx
            y = self.cur.y + by
            if y < 0:
                self.game_over = True
                self.persist_game()  # log a game over with current stats
                return
            self.board[y][x] = color
        self.clear_lines()
        self.cur = self.next
        self.next = self.new_piece()
        if not self.valid(self.cur):
            self.game_over = True
            self.persist_game()

    def clear_lines(self):
        full = [i for i in range(ROWS) if all(self.board[i][c] for c in range(COLS))]
        n = len(full)
        if n == 0:
            return
        for i in reversed(full):
            del self.board[i]
            self.board.insert(0, [None for _ in range(COLS)])
        scores = {1: 100, 2: 300, 3: 500, 4: 800}
        self.score += scores.get(n, 0) * self.level
        self.lines += n
        if self.lines // LINES_PER_LEVEL + 1 > self.level:
            self.level += 1
            self.delay = max(80, START_DELAY - LEVEL_STEP * (self.level - 1))

    def move(self, dx, dy):
        if self.paused or self.game_over:
            return
        p = self.cur.moved(dx, dy)
        if self.valid(p):
            self.cur = p
            self.draw()
        elif dy == 1:
            self.lock()
            self.draw()

    def soft_drop(self):
        if self.paused or self.game_over:
            return
        self.move(0, 1)
        self.score += 1

    def hard_drop(self):
        if self.paused or self.game_over:
            return
        dist = 0
        p = self.cur
        while True:
            q = p.moved(0, 1)
            if self.valid(q):
                p = q
                dist += 1
            else:
                break
        self.cur = p
        self.lock()
        self.score += dist * 2
        self.draw()

    def rotate(self):
        if self.paused or self.game_over:
            return
        p = self.cur.rotated()
        for k in [0, -1, 1, -2, 2]:
            c = p.moved(k, 0)
            if self.valid(c):
                self.cur = c
                self.draw()
                return

    def tick(self):
        if not self.paused and not self.game_over:
            self.move(0, 1)
        self.root.after(self.delay, self.tick)
        self.draw()

    def ghost_piece(self):
        p = Piece(self.cur.kind)
        p.rot, p.x, p.y = self.cur.rot, self.cur.x, self.cur.y
        while self.valid(p.moved(0, 1)):
            p = p.moved(0, 1)
        return p

    def draw_cell(self, x, y, color):
        x0, y0 = x * CELL, y * CELL
        x1, y1 = x0 + CELL, y0 + CELL
        self.canvas.create_rectangle(
            x0, y0, x1, y1, fill=color, outline="#222", width=1
        )
        self.canvas.create_rectangle(
            x0 + 3, y0 + 3, x1 - 3, y1 - 3, outline="#000", width=1
        )

    def draw_grid(self):
        for r in range(ROWS):
            for c in range(COLS):
                base = "#0e0e13" if (r + c) % 2 == 0 else "#101019"
                if self.board[r][c]:
                    self.draw_cell(c, r, self.board[r][c])
                else:
                    self.canvas.create_rectangle(
                        c * CELL,
                        r * CELL,
                        c * CELL + CELL,
                        r * CELL + CELL,
                        fill=base,
                        outline="#1b1b22",
                    )

    def draw_piece(self, piece, color):
        for bx, by in piece.blocks:
            x = piece.x + bx
            y = piece.y + by
            if 0 <= x < COLS and 0 <= y < ROWS:
                self.draw_cell(x, y, color)

    def draw_ghost(self):
        gho = self.ghost_piece()
        for bx, by in gho.blocks:
            x = gho.x + bx
            y = gho.y + by
            if 0 <= x < COLS and 0 <= y < ROWS:
                x0, y0 = x * CELL, y * CELL
                x1, y1 = x0 + CELL, y0 + CELL
                self.canvas.create_rectangle(
                    x0 + 4, y0 + 4, x1 - 4, y1 - 4, outline=COLORS["G"]
                )

    def draw_hud(self):
        pname = self.player_name or "-"
        text = f"Player {pname}   Score {self.score}   Lines {self.lines}   Level {self.level}"
        if self.paused:
            text += "   [PAUSED]"
        if self.game_over:
            text += "   [GAME OVER] Press R"
        self.info.config(text=text)

        # next preview
        nx0, ny0 = W - 5 * CELL, 1 * CELL
        self.canvas.create_text(
            W - 2.5 * CELL, 0.5 * CELL, text="NEXT", fill="#ddd", font=("Consolas", 12)
        )
        for bx, by in self.next.blocks:
            self.canvas.create_rectangle(
                nx0 + bx * CELL,
                ny0 + by * CELL,
                nx0 + bx * CELL + CELL,
                ny0 + by * CELL + CELL,
                fill=COLORS[self.next.kind],
                outline="#222",
            )

    def draw(self):
        self.canvas.delete("all")
        self.draw_grid()
        if not self.game_over:
            self.draw_ghost()
            self.draw_piece(self.cur, COLORS[self.cur.kind])
        self.canvas.create_rectangle(1, 1, W - 1, H - 1, outline="#444")
        self.draw_hud()

    # ===== Persistence and leaderboard =====
    def persist_game(self):
        if not self.player_name:
            return
        Game.objects.insert(
            id=None,
            name=self.player_name,
            score=int(self.score),
            lines=int(self.lines),
            level=int(self.level),
            played_at=datetime.datetime.utcnow().isoformat() + "Z",
        )

    def show_leaderboard(self):
        # Use ORM query with expressions to compute max(score) per name
        rows = (
            Game.objects.query()
            .select("name, MAX(score) AS max_score, COUNT(*) AS plays")
            .group_by("name")
            .order_by("max_score DESC")
            .limit(50)
            .all()
            .as_list()
        )
        win = tk.Toplevel(self.root)
        win.title("Leaderboard")
        cols = ("rank", "name", "max_score", "plays")
        tv = ttk.Treeview(win, columns=cols, show="headings", height=15)
        for c, w in zip(cols, (60, 160, 120, 80)):
            tv.heading(c, text=c)
            tv.column(c, width=w, anchor="center")
        tv.pack(fill="both", expand=True, padx=8, pady=8)
        for i, r in enumerate(rows, start=1):
            tv.insert(
                "", "end", values=(i, r.get("name"), r.get("max_score"), r.get("plays"))
            )


def main():
    root = tk.Tk()
    root.configure(bg="#111")
    app = Tetris(root)
    try:
        root.mainloop()
    finally:
        sql_close()


if __name__ == "__main__":
    main()
