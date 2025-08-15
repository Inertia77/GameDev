# -*- coding: utf-8 -*-
"""
Dodger — Pygame 2D 躲避小游戏（单文件，无外部素材）
作者：你和 ChatGPT
特性：
- 动态难度（时间越久，敌人越多越快）
- 护盾道具（随机掉落，吸收一次伤害）
- 冲刺（短暂无敌 + 加速，1.2s 冷却）
- 暂停/继续、最高分本地保存（highscore.json）
- 无外部图片/字体/音效依赖，纯代码绘制

运行：
    pip install pygame
    python dodger_game.py
"""

import sys, os, json, random, math, time
import pygame

# -----------------------------
# 配置
# -----------------------------
WIDTH, HEIGHT = 960, 540         # 窗口尺寸（16:9）
FPS = 60                         # 帧率
PLAYER_SIZE = 36                 # 玩家方块边长
ENEMY_SIZE = 28                  # 敌人方块边长
POWERUP_SIZE = 22                # 道具尺寸
PLAYER_SPEED = 330               # 玩家基础速度（像素/秒）
DASH_SPEED = 820                 # 冲刺速度（像素/秒）
DASH_TIME = 0.18                 # 冲刺持续秒数
DASH_COOLDOWN = 1.2              # 冲刺冷却秒数
INVINCIBLE_AFTER_HIT = 0.8       # 受伤后短暂无敌
SHIELD_DURATION_HINT = 1         # 护盾显示标记（直到被消耗）
SPAWN_BASE_INTERVAL = 0.9        # 敌人基础生成间隔（秒）
SPAWN_MIN_INTERVAL = 0.18        # 敌人最小生成间隔（秒）
SPAWN_ACCEL_TIME = 60            # 难度加速时间（越长下降越慢）
ENEMY_SPEED_BASE = 180           # 敌人基础速度（像素/秒）
ENEMY_SPEED_MAX = 560            # 敌人最大速度（像素/秒）
POWERUP_INTERVAL = (6, 11)       # 道具掉落间隔范围（秒）
HIGH_SCORE_FILE = "highscore.json"

# 颜色（深蓝/亮蓝/金色主题）
C_BG_TOP = (10, 23, 52)
C_BG_BOTTOM = (3, 8, 18)
C_GLOW = (42, 174, 224)
C_GOLD = (242, 209, 122)
C_WHITE = (240, 240, 240)
C_RED = (230, 70, 70)
C_GREEN = (30, 200, 140)
C_DIM = (140, 150, 160)

# 游戏状态
S_MENU, S_PLAY, S_PAUSE, S_GAMEOVER = range(4)

# -----------------------------
# 工具函数
# -----------------------------
def load_high_score():
    try:
        if os.path.exists(HIGH_SCORE_FILE):
            with open(HIGH_SCORE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return int(data.get("high_score", 0))
    except Exception:
        pass
    return 0

def save_high_score(score):
    try:
        with open(HIGH_SCORE_FILE, "w", encoding="utf-8") as f:
            json.dump({"high_score": int(score)}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def choose_font(size):
    # 尽力选择支持中文的系统字体，若无则退回默认
    for name in ["Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC", "Arial"]:
        try:
            return pygame.font.SysFont(name, size, bold=False)
        except Exception:
            continue
    return pygame.font.Font(None, size)

def draw_vgradient(surf, top_color, bottom_color):
    # 垂直渐变背景（GPU 友好：预渲染一次即可）
    h = surf.get_height()
    for y in range(h):
        t = y / (h - 1)
        r = int(top_color[0] * (1 - t) + bottom_color[0] * t)
        g = int(top_color[1] * (1 - t) + bottom_color[1] * t)
        b = int(top_color[2] * (1 - t) + bottom_color[2] * t)
        pygame.draw.line(surf, (r, g, b), (0, y), (surf.get_width(), y))

def glow_rect(surface, rect, color, radius=10, alpha=70):
    # 简易发光矩形（半透明外圈）
    temp = pygame.Surface((rect.width + radius*4, rect.height + radius*4), pygame.SRCALPHA)
    pygame.draw.rect(temp, (*color, alpha), (radius*2, radius*2, rect.width, rect.height), border_radius=12)
    surface.blit(temp, (rect.x - radius*2, rect.y - radius*2))

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

# -----------------------------
# 实体
# -----------------------------
class Player:
    def __init__(self):
        self.size = PLAYER_SIZE
        self.rect = pygame.Rect(WIDTH//2 - self.size//2, HEIGHT - self.size*2, self.size, self.size)
        self.speed = PLAYER_SPEED
        self.invincible_until = 0.0
        self.has_shield = False
        self.dash_until = 0.0
        self.dash_cd_until = 0.0

    def start(self):
        self.rect.centerx = WIDTH // 2
        self.rect.bottom = HEIGHT - 16
        self.invincible_until = 0
        self.dash_until = 0
        self.dash_cd_until = 0
        self.has_shield = False

    def update(self, dt, keys, now):
        vx = vy = 0.0
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            vx -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            vx += 1
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            vy -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            vy += 1

        spd = self.speed
        if now < self.dash_until:
            spd = DASH_SPEED

        # 归一化斜向速度
        if vx or vy:
            mag = math.hypot(vx, vy)
            vx, vy = vx/mag, vy/mag
        self.rect.x += int(vx * spd * dt)
        self.rect.y += int(vy * spd * dt)

        # 边界
        self.rect.x = clamp(self.rect.x, 0, WIDTH - self.size)
        self.rect.y = clamp(self.rect.y, 0, HEIGHT - self.size)

    def try_dash(self, now):
        if now >= self.dash_cd_until:
            self.dash_until = now + DASH_TIME
            self.dash_cd_until = now + DASH_COOLDOWN
            self.invincible_until = max(self.invincible_until, now + DASH_TIME * 0.9)
            return True
        return False

    def hit(self, now):
        if now < self.invincible_until:
            return False  # 无敌中
        if self.has_shield:
            self.has_shield = False
            self.invincible_until = now + INVINCIBLE_AFTER_HIT
            return False  # 护盾抵消一次
        return True  # 实际受伤（本作为一击淘汰）

    def draw(self, surf, now):
        # 主体
        col = C_GOLD if now < self.dash_until else C_WHITE
        pygame.draw.rect(surf, col, self.rect, border_radius=8)
        # 护盾环
        if self.has_shield:
            pygame.draw.rect(surf, C_GLOW, self.rect.inflate(10, 10), width=3, border_radius=12)
        # 无敌闪烁
        if now < self.invincible_until and int(now*20) % 2 == 0:
            pygame.draw.rect(surf, (255, 255, 255, 120), self.rect, border_radius=8)

class Enemy:
    def __init__(self, speed):
        self.size = ENEMY_SIZE
        x = random.randint(0, WIDTH - self.size)
        y = -self.size - random.randint(0, 200)
        self.rect = pygame.Rect(x, y, self.size, self.size)
        self.speed = speed
        self.drift = random.uniform(-60, 60)  # 水平小幅漂移

    def update(self, dt):
        self.rect.y += int(self.speed * dt)
        self.rect.x += int(self.drift * dt)
        if self.rect.left < 0 or self.rect.right > WIDTH:
            self.drift = -self.drift  # 反弹
        return self.rect.top <= HEIGHT

    def draw(self, surf):
        pygame.draw.rect(surf, C_RED, self.rect, border_radius=6)

class PowerUp:
    TYPES = ("shield",)  # 可扩展：slowmo/clear 等

    def __init__(self):
        self.kind = random.choice(self.TYPES)
        self.rect = pygame.Rect(
            random.randint(20, WIDTH - 20 - POWERUP_SIZE),
            -POWERUP_SIZE - random.randint(40, 200),
            POWERUP_SIZE, POWERUP_SIZE
        )
        self.speed = random.uniform(120, 200)

    def update(self, dt):
        self.rect.y += int(self.speed * dt)
        return self.rect.top <= HEIGHT

    def draw(self, surf):
        if self.kind == "shield":
            pygame.draw.rect(surf, C_GLOW, self.rect, border_radius=8)
            pygame.draw.rect(surf, C_WHITE, self.rect, width=2, border_radius=8)

# -----------------------------
# 游戏主类
# -----------------------------
class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Dodger — Python 2D 小游戏")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()

        # 背景预渲染
        self.bg = pygame.Surface((WIDTH, HEIGHT))
        draw_vgradient(self.bg, C_BG_TOP, C_BG_BOTTOM)

        # 字体
        self.font_big = choose_font(48)
        self.font_mid = choose_font(28)
        self.font_small = choose_font(20)

        # 音效（可选）
        self.beep = None
        try:
            pygame.mixer.init()
            # 用空音频占位（不加载外部文件）。也可以不发声。
        except Exception:
            pass

        # 状态
        self.state = S_MENU
        self.reset()

        self.high_score = load_high_score()

    def reset(self):
        self.player = Player()
        self.player.start()
        self.enemies = []
        self.powerups = []
        self.score = 0.0
        self.start_time = time.perf_counter()
        self.last_spawn = 0.0
        self.next_powerup_t = random.uniform(*POWERUP_INTERVAL)
        self.game_over_time = None

    def difficulty(self, t):
        # t：开局到现在的秒数 -> 动态难度曲线
        # 生成间隔从 SPAWN_BASE_INTERVAL 逐渐逼近 SPAWN_MIN_INTERVAL
        k = clamp(t / SPAWN_ACCEL_TIME, 0.0, 1.0)
        spawn = SPAWN_BASE_INTERVAL * (1 - k) + SPAWN_MIN_INTERVAL * k
        speed = ENEMY_SPEED_BASE * (1 - k) + ENEMY_SPEED_MAX * k
        return spawn, speed

    def spawn_enemy(self, speed):
        self.enemies.append(Enemy(speed))

    def spawn_powerup(self):
        self.powerups.append(PowerUp())

    def handle_collisions(self, now):
        # 敌人与玩家
        for e in list(self.enemies):
            if self.player.rect.colliderect(e.rect):
                if self.player.hit(now):
                    self.game_over()
                else:
                    # 被护盾抵消，删除该敌人
                    self.enemies.remove(e)

        # 道具
        for p in list(self.powerups):
            if self.player.rect.colliderect(p.rect):
                if p.kind == "shield":
                    self.player.has_shield = True
                self.powerups.remove(p)

    def game_over(self):
        self.state = S_GAMEOVER
        self.game_over_time = time.perf_counter()
        final_score = int(self.score)
        if final_score > self.high_score:
            self.high_score = final_score
            save_high_score(final_score)

    def update(self, dt):
        now = time.perf_counter()
        keys = pygame.key.get_pressed()

        if self.state == S_PLAY:
            # 玩家
            self.player.update(dt, keys, now)

            # 冲刺
            if (keys[pygame.K_SPACE] or keys[pygame.K_LCTRL]) and self.player.try_dash(now):
                pass

            # 敌人/道具生成 & 更新
            elapsed = now - self.start_time
            spawn_interval, enemy_speed = self.difficulty(elapsed)

            if (now - self.last_spawn) >= spawn_interval:
                self.last_spawn = now
                # 一次可能生成 1~2 个，后期更密集
                count = 1 + (1 if random.random() < min(0.35, elapsed/90) else 0)
                for _ in range(count):
                    self.spawn_enemy(enemy_speed * random.uniform(0.9, 1.15))

            # powerup 定时
            if elapsed >= self.next_powerup_t:
                self.spawn_powerup()
                self.next_powerup_t = elapsed + random.uniform(*POWERUP_INTERVAL)

            # 更新敌人/道具
            self.enemies = [e for e in self.enemies if e.update(dt)]
            self.powerups = [p for p in self.powerups if p.update(dt)]

            # 碰撞
            self.handle_collisions(now)

            # 计分：生存时间 * 10 + 轻微基于难度的奖励
            self.score = elapsed * 10 + max(0, (len(self.enemies) - 4))

    def draw_hud(self):
        # 分数
        score_txt = self.font_mid.render(f"Score  {int(self.score)}", True, C_WHITE)
        self.screen.blit(score_txt, (16, 12))
        # 最高分
        hs_txt = self.font_small.render(f"Best  {self.high_score}", True, C_DIM)
        self.screen.blit(hs_txt, (18, 48))
        # 冲刺冷却
        now = time.perf_counter()
        cd_left = max(0.0, self.player.dash_cd_until - now)
        dash_info = "Dash Ready" if cd_left <= 0.0 else f"Dash {cd_left:.1f}s"
        dash_txt = self.font_small.render(dash_info, True, C_GLOW if cd_left <= 0.0 else C_DIM)
        self.screen.blit(dash_txt, (16, HEIGHT - 36))
        # 提示
        tip = self.font_small.render("WASD/←→↑↓ 移动 | Space 冲刺 | P 暂停", True, C_DIM)
        self.screen.blit(tip, (WIDTH - tip.get_width() - 16, HEIGHT - 36))

    def draw(self):
        self.screen.blit(self.bg, (0, 0))

        if self.state in (S_PLAY, S_PAUSE):
            # 发光背景层（轻微动感）
            t = time.perf_counter()
            cx = WIDTH * 0.3 + math.sin(t * 0.6) * 60
            cy = HEIGHT * 0.35 + math.cos(t * 0.7) * 40
            glow_rect(self.screen, pygame.Rect(int(cx), int(cy), 220, 140), C_GLOW, alpha=40)

            # 实体
            for p in self.powerups:
                p.draw(self.screen)
            for e in self.enemies:
                e.draw(self.screen)
            self.player.draw(self.screen, time.perf_counter())
            self.draw_hud()

            if self.state == S_PAUSE:
                self.draw_center_panel("已暂停", "按 P 或 Esc 继续", footer="按 Q 退出")
        elif self.state == S_MENU:
            self.draw_title_screen()
        elif self.state == S_GAMEOVER:
            self.draw_gameover_screen()

        pygame.display.flip()

    def draw_center_panel(self, title, subtitle, footer=None):
        panel = pygame.Surface((min(640, WIDTH-120), 240), pygame.SRCALPHA)
        pygame.draw.rect(panel, (0, 0, 0, 140), panel.get_rect(), border_radius=16)
        tx = self.font_big.render(title, True, C_GOLD)
        sx = self.font_mid.render(subtitle, True, C_WHITE)
        panel.blit(tx, (panel.get_width()//2 - tx.get_width()//2, 40))
        panel.blit(sx, (panel.get_width()//2 - sx.get_width()//2, 120))
        if footer:
            fx = self.font_small.render(footer, True, C_DIM)
            panel.blit(fx, (panel.get_width()//2 - fx.get_width()//2, 180))
        self.screen.blit(panel, (WIDTH//2 - panel.get_width()//2, HEIGHT//2 - panel.get_height()//2))

    def draw_title_screen(self):
        title = self.font_big.render("Dodger", True, C_GOLD)
        tip1 = self.font_mid.render("一个用 Python+Pygame 写的 2D 躲避小游戏", True, C_WHITE)
        tip2 = self.font_mid.render("按 Enter 开始 · Q 退出", True, C_DIM)
        hs = self.font_small.render(f"最高分：{self.high_score}", True, C_DIM)
        self.screen.blit(title, (WIDTH//2 - title.get_width()//2, HEIGHT*0.28))
        self.screen.blit(tip1, (WIDTH//2 - tip1.get_width()//2, HEIGHT*0.28 + 70))
        self.screen.blit(tip2, (WIDTH//2 - tip2.get_width()//2, HEIGHT*0.28 + 120))
        self.screen.blit(hs, (WIDTH//2 - hs.get_width()//2, HEIGHT*0.28 + 170))

    def draw_gameover_screen(self):
        final = int(self.score)
        t1 = self.font_big.render("游戏结束", True, C_GOLD)
        t2 = self.font_mid.render(f"本局得分：{final}", True, C_WHITE)
        t3 = self.font_mid.render("按 R 重开 · Q 退出", True, C_DIM)
        self.screen.blit(t1, (WIDTH//2 - t1.get_width()//2, HEIGHT*0.32))
        self.screen.blit(t2, (WIDTH//2 - t2.get_width()//2, HEIGHT*0.32 + 70))
        self.screen.blit(t3, (WIDTH//2 - t3.get_width()//2, HEIGHT*0.32 + 120))

    def run(self):
        while True:
            dt = self.clock.tick(FPS) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit(); sys.exit()
                if event.type == pygame.KEYDOWN:
                    if self.state == S_MENU:
                        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                            self.state = S_PLAY
                            self.reset()
                        elif event.key in (pygame.K_ESCAPE, pygame.K_q):
                            pygame.quit(); sys.exit()
                    elif self.state == S_PLAY:
                        if event.key in (pygame.K_p, pygame.K_ESCAPE):
                            self.state = S_PAUSE
                        elif event.key == pygame.K_SPACE:
                            self.player.try_dash(time.perf_counter())
                    elif self.state == S_PAUSE:
                        if event.key in (pygame.K_p, pygame.K_ESCAPE):
                            self.state = S_PLAY
                        elif event.key in (pygame.K_q,):
                            pygame.quit(); sys.exit()
                    elif self.state == S_GAMEOVER:
                        if event.key in (pygame.K_r,):
                            self.state = S_PLAY
                            self.reset()
                        elif event.key in (pygame.K_q, pygame.K_ESCAPE):
                            pygame.quit(); sys.exit()

            if self.state == S_PLAY:
                self.update(dt)

            self.draw()

# -----------------------------
# 入口
# -----------------------------
if __name__ == "__main__":
    Game().run()
