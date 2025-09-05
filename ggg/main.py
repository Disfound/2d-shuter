import math
import random
import sys
from dataclasses import dataclass
import json
from pathlib import Path

import pygame
from pygame import Vector2


# -----------------------------
# Config
# -----------------------------
WINDOW_WIDTH = 960
WINDOW_HEIGHT = 540
FPS = 60

PLAYER_SPEED = 280.0
PLAYER_RADIUS = 16
PLAYER_MAX_HEALTH = 5

BULLET_SPEED = 600.0
BULLET_RADIUS = 4
BULLET_COOLDOWN_SEC = 0.12
BULLET_LIFETIME_SEC = 1.2

ENEMY_SPEED_MIN = 80.0
ENEMY_SPEED_MAX = 140.0
ENEMY_RADIUS = 14
ENEMY_SPAWN_EVERY_SEC = 1.1
ENEMY_SPAWN_ACCEL_EVERY_SEC = 20.0
ENEMY_SPAWN_ACCEL_FACTOR = 0.92  # каждые X секунд, спавн быстрее

INVULN_ON_HIT_SEC = 0.6

BACKGROUND_COLOR = (18, 18, 22)
PLAYER_COLOR = (80, 200, 255)
PLAYER_HIT_COLOR = (255, 120, 120)
BULLET_COLOR = (255, 235, 59)
ENEMY_COLOR = (255, 85, 85)
TEXT_COLOR = (230, 230, 240)
UI_ACCENT = (120, 255, 170)
COIN_COLOR = (255, 215, 0)
ARMOR_COLOR = (120, 180, 255)

# Levels & bosses
LEVEL_KILLS_TO_BOSS_BASE = 30
LEVEL_KILLS_TO_BOSS_INC = 10
NORMAL_DROP_CHANCE = 0.30  # шанс дропа монеты с обычного врага


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


def circle_intersects_circle(center_a: Vector2, radius_a: float, center_b: Vector2, radius_b: float) -> bool:
    return center_a.distance_to(center_b) <= (radius_a + radius_b)


@dataclass
class Bullet:
    position: Vector2
    velocity: Vector2
    radius: float
    pierce_remaining: int
    lifetime: float = BULLET_LIFETIME_SEC
    damage: int = 1

    def update(self, dt: float) -> None:
        self.position += self.velocity * dt
        self.lifetime -= dt

    def is_alive(self) -> bool:
        if self.lifetime <= 0:
            return False
        x, y = self.position
        return -50 <= x <= WINDOW_WIDTH + 50 and -50 <= y <= WINDOW_HEIGHT + 50

    def draw(self, surface: pygame.Surface) -> None:
        pygame.draw.circle(surface, BULLET_COLOR, self.position, self.radius)


@dataclass
class Enemy:
    position: Vector2
    speed: float
    radius: float = ENEMY_RADIUS
    max_health: int = 1
    health: int = 1
    is_boss: bool = False

    def update(self, dt: float, target: Vector2) -> None:
        to_target = (target - self.position)
        if to_target.length_squared() > 1e-6:
            direction = to_target.normalize()
            self.position += direction * self.speed * dt

    def draw(self, surface: pygame.Surface) -> None:
        pygame.draw.circle(surface, ENEMY_COLOR, self.position, self.radius)
        if self.max_health > 1:
            # health bar
            w = max(22, int(self.radius * 2))
            h = 5
            x = int(self.position.x - w / 2)
            y = int(self.position.y - self.radius - 10)
            pygame.draw.rect(surface, (50, 50, 56), (x, y, w, h))
            ratio = max(0.0, self.health / self.max_health)
            pygame.draw.rect(surface, (255, 120, 120), (x, y, int(w * ratio), h))


class ShooterEnemy(Enemy):
    def __init__(self, position: Vector2, speed: float, radius: float = ENEMY_RADIUS, max_health: int = 3, cooldown: float = 1.6):
        super().__init__(position=position, speed=speed, radius=radius, max_health=max_health, health=max_health, is_boss=False)
        self.shoot_timer = cooldown
        self.shoot_cooldown = cooldown

    def update(self, dt: float, target: Vector2) -> None:
        super().update(dt, target)
        self.shoot_timer -= dt

    def ready_to_shoot(self) -> bool:
        return self.shoot_timer <= 0

    def reset_shoot(self) -> None:
        self.shoot_timer = self.shoot_cooldown


@dataclass
class EnemyBullet:
    position: Vector2
    velocity: Vector2
    radius: float = 3.0
    lifetime: float = 3.0

    def update(self, dt: float) -> None:
        self.position += self.velocity * dt
        self.lifetime -= dt

    def is_alive(self) -> bool:
        if self.lifetime <= 0:
            return False
        x, y = self.position
        return -20 <= x <= WINDOW_WIDTH + 20 and -20 <= y <= WINDOW_HEIGHT + 20

    def draw(self, surface: pygame.Surface) -> None:
        pygame.draw.circle(surface, (255, 160, 90), self.position, self.radius)


@dataclass
class Explosion:
    position: Vector2
    radius: float
    max_radius: float
    damage: int
    lifetime: float
    
    def update(self, dt: float) -> None:
        self.lifetime -= dt
        self.radius = self.max_radius * (1.0 - self.lifetime / 0.3)
    
    def is_alive(self) -> bool:
        return self.lifetime > 0
    
    def draw(self, surface: pygame.Surface) -> None:
        alpha = int(255 * (self.lifetime / 0.3))
        color = (255, 100, 0, alpha)
        pygame.draw.circle(surface, color, self.position, self.radius, 3)


class Player:
    def __init__(self, position: Vector2):
        self.position = Vector2(position)
        self.radius = PLAYER_RADIUS
        self.health = PLAYER_MAX_HEALTH
        self.invuln_timer = 0.0
        self.shoot_cooldown = 0.0
        # Currency and upgrades
        self.coins = 0
        self.speed_multiplier = 1.0
        self.fire_rate_multiplier = 1.0  # >1.0 = быстрее стрельба
        self.bullet_size_level = 0
        self.bullet_pierce_level = 0
        self.magnet_radius = 60.0
        self.max_health_bonus = 0
        self.armor = 0  # поглощает урон перед здоровьем
        self.bullet_damage_level = 0
        self.coin_gain_level = 0
        # extra item-shop upgrades
        self.dodge_level = 0
        self.regen_level = 0
        self.lifesteal_level = 0
        self.crit_level = 0
        self.aoe_on_kill_level = 0
        self.magnet_bonus_level = 0
        self.bullet_speed_level = 0
        self._regen_timer = 0.0
        self.bullet_speed_multiplier = 1.0
        self._lifesteal_kills = 0  # counter for lifesteal

    def update(self, dt: float, keys: pygame.key.ScancodeWrapper) -> None:
        move = Vector2(0, 0)
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            move.y -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            move.y += 1
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            move.x -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            move.x += 1

        if move.length_squared() > 0:
            move = move.normalize() * PLAYER_SPEED * self.speed_multiplier
        self.position += move * dt

        self.position.x = clamp(self.position.x, self.radius, WINDOW_WIDTH - self.radius)
        self.position.y = clamp(self.position.y, self.radius, WINDOW_HEIGHT - self.radius)

        if self.invuln_timer > 0:
            self.invuln_timer -= dt
        if self.shoot_cooldown > 0:
            self.shoot_cooldown -= dt
        # passive regen
        if self.regen_level > 0 and self.health < self.max_health():
            self._regen_timer += dt
            # heal 1 HP every base 12s improved by level
            interval = max(4.0, 12.0 - 1.6 * self.regen_level)
            if self._regen_timer >= interval:
                self._regen_timer = 0.0
                self.health = min(self.max_health(), self.health + 1)

    def max_health(self) -> int:
        return PLAYER_MAX_HEALTH + self.max_health_bonus

    def try_shoot(self, aim_pos: Vector2) -> Bullet | None:
        if self.shoot_cooldown > 0:
            return None
        direction = aim_pos - self.position
        if direction.length_squared() <= 1e-6:
            return None
        direction = direction.normalize()
        speed_mult = self.bullet_speed_multiplier * (1.0 + 0.08 * self.bullet_speed_level)
        velocity = direction * BULLET_SPEED * speed_mult
        # apply fire rate and size/pierce
        cooldown = BULLET_COOLDOWN_SEC / self.fire_rate_multiplier
        self.shoot_cooldown = max(0.02, cooldown)
        size_multiplier = 1.0 + 0.35 * self.bullet_size_level
        radius = BULLET_RADIUS * size_multiplier
        pierce = self.bullet_pierce_level
        dmg = 1 + self.bullet_damage_level
        return Bullet(position=Vector2(self.position), velocity=velocity, radius=radius, pierce_remaining=pierce, damage=dmg)

    def take_hit(self) -> None:
        if self.invuln_timer > 0:
            return
        # dodge chance
        if self.dodge_level > 0 and random.random() < min(0.5, 0.05 * self.dodge_level):
            self.invuln_timer = 0.2
            return
        if self.armor > 0:
            self.armor -= 1
        else:
            self.health -= 1
        self.invuln_timer = INVULN_ON_HIT_SEC
    
    def on_kill(self) -> None:
        """Called when player kills an enemy - handles lifesteal"""
        if self.lifesteal_level > 0:
            self._lifesteal_kills += 1
            # heal every N kills based on level
            heal_interval = max(1, 5 - self.lifesteal_level)
            if self._lifesteal_kills >= heal_interval:
                self._lifesteal_kills = 0
                self.health = min(self.max_health(), self.health + 1)

    def is_alive(self) -> bool:
        return self.health > 0

    def draw(self, surface: pygame.Surface, aim_pos: Vector2) -> None:
        color = PLAYER_HIT_COLOR if self.invuln_timer > 0 and int(self.invuln_timer * 20) % 2 == 0 else PLAYER_COLOR
        pygame.draw.circle(surface, color, self.position, self.radius)
        # направление взгляда/прицела
        to_aim = aim_pos - self.position
        if to_aim.length_squared() > 1e-6:
            dir_norm = to_aim.normalize()
            tip = self.position + dir_norm * (self.radius + 8)
            pygame.draw.line(surface, color, self.position, tip, 3)


@dataclass
class Coin:
    position: Vector2
    value: int
    velocity: Vector2
    radius: float = 6.0

    def update(self, dt: float, player_pos: Vector2, magnet_radius: float) -> None:
        # простая физика + магнит
        # замедляем естественное движение
        self.velocity *= 0.98

        to_player = player_pos - self.position
        dist_sq = to_player.length_squared()
        if dist_sq < magnet_radius * magnet_radius:
            if dist_sq > 1e-4:
                pull = to_player.normalize() * 600.0
                self.velocity += pull * dt
        self.position += self.velocity * dt
        # keep inside window bounds
        if self.position.x < self.radius:
            self.position.x = self.radius
            self.velocity.x = 0
        if self.position.x > WINDOW_WIDTH - self.radius:
            self.position.x = WINDOW_WIDTH - self.radius
            self.velocity.x = 0
        if self.position.y < self.radius:
            self.position.y = self.radius
            self.velocity.y = 0
        if self.position.y > WINDOW_HEIGHT - self.radius:
            self.position.y = WINDOW_HEIGHT - self.radius
            self.velocity.y = 0

    def draw(self, surface: pygame.Surface) -> None:
        pygame.draw.circle(surface, COIN_COLOR, self.position, self.radius)
        pygame.draw.circle(surface, (140, 110, 0), self.position, self.radius, 1)


class EnemySpawner:
    def __init__(self):
        self.timer = ENEMY_SPAWN_EVERY_SEC
        self.current_interval = ENEMY_SPAWN_EVERY_SEC
        self.accel_timer = 0.0
        self.level = 1
        self.kills_this_level = 0
        self.boss_active = False
        self.level_transition_timer = 0.0  # freeze time when level changes
        self.boss_banner_timer = 0.0  # show BOSS banner briefly

    def update(self, dt: float) -> None:
        if self.level_transition_timer > 0:
            self.level_transition_timer -= dt
            return
        self.timer -= dt
        self.accel_timer += dt
        if self.accel_timer >= ENEMY_SPAWN_ACCEL_EVERY_SEC:
            self.accel_timer = 0.0
            self.current_interval = max(0.25, self.current_interval * ENEMY_SPAWN_ACCEL_FACTOR)

    def should_spawn(self) -> bool:
        return self.timer <= 0.0 and self.level_transition_timer <= 0.0

    def reset(self) -> None:
        self.timer = self.current_interval

    def spawn_enemy(self) -> Enemy:
        side = random.choice(["top", "bottom", "left", "right"])
        if side == "top":
            pos = Vector2(random.uniform(0, WINDOW_WIDTH), -ENEMY_RADIUS * 2)
        elif side == "bottom":
            pos = Vector2(random.uniform(0, WINDOW_WIDTH), WINDOW_HEIGHT + ENEMY_RADIUS * 2)
        elif side == "left":
            pos = Vector2(-ENEMY_RADIUS * 2, random.uniform(0, WINDOW_HEIGHT))
        else:
            pos = Vector2(WINDOW_WIDTH + ENEMY_RADIUS * 2, random.uniform(0, WINDOW_HEIGHT))

        # scale base enemies per level: +6% speed, +HP every 3 levels
        speed = random.uniform(ENEMY_SPEED_MIN, ENEMY_SPEED_MAX) * (1.0 + 0.06 * (self.level - 1))
        # chance to spawn shooter enemy starting from level 2
        if self.level >= 2 and random.random() < min(0.20 + 0.04 * (self.level - 2), 0.55):
            return ShooterEnemy(position=pos, speed=speed * 0.95, radius=ENEMY_RADIUS + 2, max_health=3 + (self.level // 2), cooldown=max(0.9, 1.6 - 0.06 * self.level))
        hp = 1 + ((self.level - 1) // 3)
        return Enemy(position=pos, speed=speed, max_health=hp, health=hp)

    def should_spawn_boss(self) -> bool:
        if self.boss_active:
            return False
        need = LEVEL_KILLS_TO_BOSS_BASE + (self.level - 1) * LEVEL_KILLS_TO_BOSS_INC
        return self.kills_this_level >= need

    def spawn_boss(self, player_pos: Vector2) -> Enemy:
        # big enemy with high health
        self.boss_active = True
        self.boss_banner_timer = 1.0
        side = random.choice(["top", "bottom", "left", "right"])
        if side == "top":
            pos = Vector2(WINDOW_WIDTH / 2, -ENEMY_RADIUS * 4)
        elif side == "bottom":
            pos = Vector2(WINDOW_WIDTH / 2, WINDOW_HEIGHT + ENEMY_RADIUS * 4)
        elif side == "left":
            pos = Vector2(-ENEMY_RADIUS * 4, WINDOW_HEIGHT / 2)
        else:
            pos = Vector2(WINDOW_WIDTH + ENEMY_RADIUS * 4, WINDOW_HEIGHT / 2)
        base_hp = 280 + 120 * (self.level - 1)
        boss = Enemy(position=pos, speed=random.uniform(100, 140), radius=34, max_health=base_hp, health=base_hp, is_boss=True)
        return boss

    def on_boss_killed(self) -> None:
        self.level += 1
        self.kills_this_level = 0
        self.boss_active = False
        # слегка ускоряем темп и сбрасываем таймер спавна, чтобы игра продолжилась сразу
        self.current_interval = max(0.25, self.current_interval * 0.95)
        self.timer = self.current_interval
        self.level_transition_timer = 1.2


def draw_console(surface: pygame.Surface, font: pygame.font.Font, console_text: str, history: list[str]) -> None:
    """Draw console overlay"""
    overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 180))
    surface.blit(overlay, (0, 0))
    
    # Console panel
    panel_w, panel_h = 800, 400
    panel_rect = pygame.Rect((WINDOW_WIDTH - panel_w) // 2, (WINDOW_HEIGHT - panel_h) // 2, panel_w, panel_h)
    pygame.draw.rect(surface, (20, 20, 25), panel_rect, border_radius=8)
    pygame.draw.rect(surface, (60, 60, 70), panel_rect, 2, border_radius=8)
    
    # Title
    title = font.render("КОНСОЛЬ (F1 - закрыть)", True, (120, 255, 170))
    surface.blit(title, (panel_rect.left + 10, panel_rect.top + 10))
    
    # History
    y = panel_rect.top + 40
    for line in history[-15:]:  # Show last 15 lines
        text = font.render(line, True, (200, 200, 200))
        surface.blit(text, (panel_rect.left + 10, y))
        y += 20
    
    # Current input
    input_text = font.render(f"> {console_text}_", True, (255, 255, 255))
    surface.blit(input_text, (panel_rect.left + 10, y + 10))
    
    # Help
    help_text = font.render("Команды: help, god, money, level, killall, spawn, heal, armor", True, (150, 150, 150))
    surface.blit(help_text, (panel_rect.left + 10, panel_rect.bottom - 25))


def draw_admin_panel(surface: pygame.Surface, font: pygame.font.Font, admin_input: str, authenticated: bool) -> None:
    """Draw admin panel"""
    overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 200))
    surface.blit(overlay, (0, 0))
    
    panel_w, panel_h = 400, 200
    panel_rect = pygame.Rect((WINDOW_WIDTH - panel_w) // 2, (WINDOW_HEIGHT - panel_h) // 2, panel_w, panel_h)
    pygame.draw.rect(surface, (30, 20, 20), panel_rect, border_radius=8)
    pygame.draw.rect(surface, (100, 60, 60), panel_rect, 2, border_radius=8)
    
    if not authenticated:
        title = font.render("АДМИН ПАНЕЛЬ", True, (255, 100, 100))
        surface.blit(title, (panel_rect.left + 10, panel_rect.top + 10))
        
        pass_text = font.render("Пароль:", True, (200, 200, 200))
        surface.blit(pass_text, (panel_rect.left + 10, panel_rect.top + 50))
        
        input_text = font.render(f"{admin_input}_", True, (255, 255, 255))
        surface.blit(input_text, (panel_rect.left + 10, panel_rect.top + 80))
        
        hint = font.render("Enter - войти, ESC - отмена", True, (150, 150, 150))
        surface.blit(hint, (panel_rect.left + 10, panel_rect.bottom - 30))
    else:
        title = font.render("АДМИН ПАНЕЛЬ - АВТОРИЗОВАН", True, (100, 255, 100))
        surface.blit(title, (panel_rect.left + 10, panel_rect.top + 10))
        
        options = [
            "1 - God Mode (бессмертие)",
            "2 - +1000 монет",
            "3 - +10 уровень",
            "4 - Убить всех врагов",
            "5 - Полное лечение",
            "6 - +10 брони",
            "7 - Показать команды консоли",
            "ESC - закрыть"
        ]
        
        y = panel_rect.top + 50
        for option in options:
            text = font.render(option, True, (200, 200, 200))
            surface.blit(text, (panel_rect.left + 10, y))
            y += 20


def execute_console_command(command: str, player: Player, enemies: list, spawner: EnemySpawner) -> str:
    """Execute console command and return result message"""
    cmd = command.strip().lower()
    
    if cmd == "help":
        return "Команды: god, money, level, killall, spawn, heal, armor"
    elif cmd == "god":
        player.health = 999
        player.armor = 999
        return "God mode активирован!"
    elif cmd == "money":
        player.coins += 1000
        return "Добавлено 1000 монет"
    elif cmd == "level":
        spawner.level += 10
        return f"Уровень повышен до {spawner.level}"
    elif cmd == "killall":
        enemies.clear()
        return "Все враги уничтожены"
    elif cmd == "spawn":
        # Spawn 5 enemies
        for _ in range(5):
            side = random.choice(["top", "bottom", "left", "right"])
            if side == "top":
                pos = Vector2(random.uniform(0, WINDOW_WIDTH), -ENEMY_RADIUS)
            elif side == "bottom":
                pos = Vector2(random.uniform(0, WINDOW_WIDTH), WINDOW_HEIGHT + ENEMY_RADIUS)
            elif side == "left":
                pos = Vector2(-ENEMY_RADIUS, random.uniform(0, WINDOW_HEIGHT))
            else:
                pos = Vector2(WINDOW_WIDTH + ENEMY_RADIUS, random.uniform(0, WINDOW_HEIGHT))
            enemies.append(Enemy(position=pos, speed=random.uniform(ENEMY_SPEED_MIN, ENEMY_SPEED_MAX)))
        return "Заспавнено 5 врагов"
    elif cmd == "heal":
        player.health = player.max_health()
        return "Здоровье восстановлено"
    elif cmd == "armor":
        player.armor += 10
        return "Добавлено 10 брони"
    else:
        return f"Неизвестная команда: {command}"


def draw_text(surface: pygame.Surface, text: str, pos: tuple[int, int], font: pygame.font.Font, color=TEXT_COLOR) -> None:
    surf = font.render(text, True, color)
    surface.blit(surf, pos)


def draw_ui(surface: pygame.Surface, font: pygame.font.Font, score: int, player: Player) -> None:
    draw_text(surface, f"Score: {score}", (14, 10), font)
    # здоровье
    heart_w = 18
    heart_h = 10
    for i in range(player.max_health()):
        x = 14 + i * (heart_w + 6)
        y = 38
        fill = UI_ACCENT if i < player.health else (80, 90, 100)
        pygame.draw.rect(surface, (60, 66, 74), (x - 1, y - 1, heart_w + 2, heart_h + 2), 1)
        pygame.draw.rect(surface, fill, (x, y, heart_w, heart_h))
    # монеты
    coin_text = f"Coins: {player.coins}"
    surf = font.render(coin_text, True, COIN_COLOR)
    rect = surf.get_rect(topright=(WINDOW_WIDTH - 14, 10))
    surface.blit(surf, rect)
    # броня
    if player.armor > 0:
        armor_text = f"Armor: {player.armor}"
        a_surf = font.render(armor_text, True, ARMOR_COLOR)
        a_rect = a_surf.get_rect(topright=(WINDOW_WIDTH - 14, 34))
        surface.blit(a_surf, a_rect)


def draw_level_progress(surface: pygame.Surface, font: pygame.font.Font, spawner: EnemySpawner) -> None:
    need = LEVEL_KILLS_TO_BOSS_BASE + (spawner.level - 1) * LEVEL_KILLS_TO_BOSS_INC
    x, y, w, h = 14, 78, 260, 12
    if spawner.boss_active:
        label = font.render("Босс!", True, (255, 120, 120))
        surface.blit(label, (x, y - 2))
        return
    # bar bg
    pygame.draw.rect(surface, (60, 66, 74), (x, y, w, h))
    ratio = 0.0 if need <= 0 else max(0.0, min(1.0, spawner.kills_this_level / need))
    pygame.draw.rect(surface, UI_ACCENT, (x, y, int(w * ratio), h))
    text = font.render(f"До босса: {min(spawner.kills_this_level, need)}/{need}", True, (210, 210, 220))
    surface.blit(text, (x + w + 10, y - 4))


def draw_shop(surface: pygame.Surface, big_font: pygame.font.Font, font: pygame.font.Font, player: Player, shop_info: dict, speed_levels: int, firerate_levels: int, page: int) -> list[pygame.Rect]:
    overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 200))
    surface.blit(overlay, (0, 0))

    panel_w, panel_h = 720, 360
    panel_rect = pygame.Rect((WINDOW_WIDTH - panel_w) // 2, (WINDOW_HEIGHT - panel_h) // 2, panel_w, panel_h)
    pygame.draw.rect(surface, (32, 36, 42), panel_rect, border_radius=10)
    pygame.draw.rect(surface, (80, 86, 96), panel_rect, 2, border_radius=10)

    title = big_font.render("МАГАЗИН", True, UI_ACCENT)
    title_rect = title.get_rect(midtop=(panel_rect.centerx, panel_rect.top + 18))
    surface.blit(title, title_rect)

    coins_text = font.render(f"Монеты: {player.coins}", True, COIN_COLOR)
    coins_rect = coins_text.get_rect(topright=(panel_rect.right - 14, panel_rect.top + 24))
    surface.blit(coins_text, coins_rect)

    if page == 0:
        items = [
            ("1) Скорость", speed_levels, shop_info["speed_cost"], "+12% к скорости"),
            ("2) Скорострельность", firerate_levels, shop_info["firerate_cost"], "+15% к скорострельности"),
            ("3) Пробитие", player.bullet_pierce_level, shop_info["pierce_cost"], "+1 пробитие"),
            ("4) Размер пули", player.bullet_size_level, shop_info["size_cost"], "+35% радиус"),
            ("5) Магнит", int((player.magnet_radius - 60) / 60), shop_info["magnet_cost"], "+60px радиус притяжения"),
            ("6) Макс. здоровье", player.max_health_bonus, shop_info["hp_cost"], "+1 к макс. HP (и лечит 1)"),
        ]
    else:
        items = [
            ("7) Урон пули", player.bullet_damage_level, shop_info["dmg_cost"], "+1 урон"),
            ("8) Доход монет", player.coin_gain_level, shop_info["coin_cost"], "шанс +1 к монете"),
        ]

    button_rects: list[pygame.Rect] = []
    y = panel_rect.top + 80
    for idx, (label, level, cost, desc) in enumerate(items):
        afford = player.coins >= cost and cost > 0
        disabled = cost == 0
        bg = (46, 52, 60) if afford else (36, 40, 46)
        outline = (120, 130, 140) if afford else (80, 86, 96)
        btn_rect = pygame.Rect(panel_rect.left + 24, y, panel_w - 48, 44)
        # hover effect
        if btn_rect.collidepoint(pygame.mouse.get_pos()):
            bg = (56, 62, 70) if afford else (44, 48, 54)
        pygame.draw.rect(surface, bg, btn_rect, border_radius=8)
        pygame.draw.rect(surface, outline, btn_rect, 2, border_radius=8)

        left_text = font.render(f"{label}", True, (230, 230, 240))
        level_text = font.render(f"Уровень: {level}", True, UI_ACCENT if not disabled else (150,150,150))
        desc_text = font.render(desc, True, (200, 200, 210))
        cost_color = COIN_COLOR if afford else (160, 140, 80)
        cost_text = font.render(f"Цена: {cost}", True, cost_color)

        surface.blit(left_text, (btn_rect.left + 14, btn_rect.top + 4))
        surface.blit(desc_text, (btn_rect.left + 14, btn_rect.top + 22))
        surface.blit(level_text, (btn_rect.centerx, btn_rect.top + 4))
        surface.blit(cost_text, (btn_rect.right - 120, btn_rect.top + 10))

        button_rects.append(btn_rect)
        y += 52

    page_text = font.render(f"Стр. {page+1}/2  ←/→", True, (200, 200, 210))
    page_rect = page_text.get_rect(center=(panel_rect.centerx, panel_rect.bottom - 32))
    surface.blit(page_text, page_rect)
    hint = font.render("Кликай по кнопкам. B — закрыть. ←/→ — страница.", True, (210, 210, 220))
    hint_rect = hint.get_rect(midbottom=(panel_rect.centerx, panel_rect.bottom - 10))
    surface.blit(hint, hint_rect)

    return button_rects


def game_over_screen(surface: pygame.Surface, big_font: pygame.font.Font, font: pygame.font.Font, score: int) -> None:
    overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 140))
    surface.blit(overlay, (0, 0))

    title = big_font.render("GAME OVER", True, (255, 120, 120))
    title_rect = title.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 - 40))
    surface.blit(title, title_rect)

    msg = font.render("Нажмите R для перезапуска, ESC — выход", True, TEXT_COLOR)
    msg_rect = msg.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 10))
    surface.blit(msg, msg_rect)

    score_surf = font.render(f"Счёт: {score}", True, UI_ACCENT)
    score_rect = score_surf.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 40))
    surface.blit(score_surf, score_rect)


def run() -> None:
    pygame.init()
    pygame.display.set_caption("Top-Down Shooter")
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    global WINDOW_WIDTH, WINDOW_HEIGHT
    WINDOW_WIDTH, WINDOW_HEIGHT = screen.get_size()
    clock = pygame.time.Clock()

    font = pygame.font.SysFont("consolas", 20)
    big_font = pygame.font.SysFont("consolas", 48, bold=True)
    
    # Console and admin panel
    console_open = False
    admin_panel_open = False
    console_text = ""
    console_history = []
    admin_password = "qweasd"
    admin_input = ""
    admin_authenticated = False

    while True:
        # Состояние матча
        player = Player(Vector2(WINDOW_WIDTH / 2, WINDOW_HEIGHT / 2))
        bullets: list[Bullet] = []
        enemies: list[Enemy] = []
        coins: list[Coin] = []
        explosions: list[Explosion] = []
        spawner = EnemySpawner()
        score = 0
        shop_open = False
        shop_page = 0
        paused = False
        item_shop_open = False
        item_click_block = False
        enemy_bullets: list[EnemyBullet] = []

        # try load save
        save_path = Path('save.json')
        if save_path.exists():
            try:
                data = json.load(open(save_path, 'r', encoding='utf-8'))
                player.coins = int(data.get('coins', 0))
                player.speed_multiplier = float(data.get('speed_multiplier', 1.0))
                player.fire_rate_multiplier = float(data.get('fire_rate_multiplier', 1.0))
                player.bullet_size_level = int(data.get('bullet_size_level', 0))
                player.bullet_pierce_level = int(data.get('bullet_pierce_level', 0))
                player.magnet_radius = float(data.get('magnet_radius', 60.0))
                player.max_health_bonus = int(data.get('max_health_bonus', 0))
                player.armor = int(data.get('armor', 0))
                player.bullet_damage_level = int(data.get('bullet_damage_level', 0))
                player.coin_gain_level = int(data.get('coin_gain_level', 0))
                # restore to full health based on max health
                player.health = player.max_health()
                # preload upgrade counters for shop
                loaded_speed = int(data.get('speed_levels', 0))
                loaded_firerate = int(data.get('firerate_levels', 0))
                loaded_pierce = int(data.get('pierce_levels', 0))
                loaded_size = int(data.get('size_levels', 0))
                loaded_magnet = int(data.get('magnet_levels', 0))
                loaded_hp = int(data.get('hp_levels', 0))
            except Exception:
                loaded_speed = loaded_firerate = loaded_pierce = loaded_size = loaded_magnet = loaded_hp = 0
        else:
            loaded_speed = loaded_firerate = loaded_pierce = loaded_size = loaded_magnet = loaded_hp = 0

        # магазин — начальные цены и лимиты (из сохранения)
        speed_levels = loaded_speed
        firerate_levels = loaded_firerate
        pierce_levels = loaded_pierce
        size_levels = loaded_size
        magnet_levels = loaded_magnet
        hp_levels = loaded_hp

        def compute_costs() -> dict:
            return {
                "speed_cost": [10, 20, 35, 55][speed_levels] if speed_levels < 4 else 0,
                "firerate_cost": [12, 24, 40, 60, 85][firerate_levels] if firerate_levels < 5 else 0,
                "pierce_cost": [15, 30, 50][pierce_levels] if pierce_levels < 3 else 0,
                "size_cost": [12, 24, 40][size_levels] if size_levels < 3 else 0,
                "magnet_cost": [10, 20, 32, 48][magnet_levels] if magnet_levels < 4 else 0,
                "hp_cost": [20, 40, 70, 110, 160][hp_levels] if hp_levels < 5 else 0,
                "dmg_cost": [18, 36, 60, 90, 130][player.bullet_damage_level] if player.bullet_damage_level < 5 else 0,
                "coin_cost": [14, 28, 50][player.coin_gain_level] if player.coin_gain_level < 3 else 0,
            }

        def save_state() -> None:
            try:
                json.dump({
                    'coins': player.coins,
                    'speed_multiplier': player.speed_multiplier,
                    'fire_rate_multiplier': player.fire_rate_multiplier,
                    'bullet_size_level': player.bullet_size_level,
                    'bullet_pierce_level': player.bullet_pierce_level,
                    'magnet_radius': player.magnet_radius,
                    'max_health_bonus': player.max_health_bonus,
                    'armor': player.armor,
                    'bullet_damage_level': player.bullet_damage_level,
                    'coin_gain_level': player.coin_gain_level,
                    'speed_levels': speed_levels,
                    'firerate_levels': firerate_levels,
                    'pierce_levels': pierce_levels,
                    'size_levels': size_levels,
                    'magnet_levels': magnet_levels,
                    'hp_levels': hp_levels,
                }, open('save.json', 'w', encoding='utf-8'))
            except Exception:
                pass

        running = True
        while running:
            dt_ms = clock.tick(FPS)
            dt = dt_ms / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)
                if event.type == pygame.KEYDOWN:
                    # Console and admin panel handling
                    if console_open:
                        if event.key == pygame.K_F1:
                            console_open = False
                        elif event.key == pygame.K_RETURN:
                            if console_text.strip():
                                result = execute_console_command(console_text, player, enemies, spawner)
                                console_history.append(f"> {console_text}")
                                console_history.append(result)
                                console_text = ""
                        elif event.key == pygame.K_BACKSPACE:
                            console_text = console_text[:-1]
                        else:
                            if event.unicode and event.unicode.isprintable():
                                console_text += event.unicode
                        continue
                    
                    if admin_panel_open:
                        if event.key == pygame.K_ESCAPE:
                            admin_panel_open = False
                            admin_authenticated = False
                            admin_input = ""
                        elif not admin_authenticated:
                            if event.key == pygame.K_RETURN:
                                if admin_input == admin_password:
                                    admin_authenticated = True
                                else:
                                    admin_input = ""
                            elif event.key == pygame.K_BACKSPACE:
                                admin_input = admin_input[:-1]
                            else:
                                if event.unicode and event.unicode.isprintable():
                                    admin_input += event.unicode
                        else:
                            # Admin commands
                            if event.key == pygame.K_1:
                                player.health = 999
                                player.armor = 999
                            elif event.key == pygame.K_2:
                                player.coins += 1000
                            elif event.key == pygame.K_3:
                                spawner.level += 10
                            elif event.key == pygame.K_4:
                                enemies.clear()
                            elif event.key == pygame.K_5:
                                player.health = player.max_health()
                            elif event.key == pygame.K_6:
                                player.armor += 10
                            elif event.key == pygame.K_7:
                                # Show console commands
                                console_history.append("=== КОМАНДЫ КОНСОЛИ ===")
                                console_history.append("help - Показать все команды")
                                console_history.append("god - God mode (999 HP + 999 armor)")
                                console_history.append("money - Добавить 1000 монет")
                                console_history.append("level - Увеличить уровень на 10")
                                console_history.append("killall - Убить всех врагов")
                                console_history.append("spawn - Заспавнить 5 врагов")
                                console_history.append("heal - Полное восстановление здоровья")
                                console_history.append("armor - Добавить 10 брони")
                                console_history.append("========================")
                        continue
                    
                    if event.key == pygame.K_F1:
                        console_open = True
                        console_text = ""
                    elif event.key == pygame.K_F2:
                        admin_panel_open = True
                        admin_input = ""
                        admin_authenticated = False
                    elif event.key == pygame.K_ESCAPE:
                        # toggle pause regardless of alive state; exit only via pause menu (Q)
                        paused = not paused
                        if paused:
                            shop_open = False
                        continue
                    if event.key == pygame.K_b and player.is_alive():
                        if not paused:
                            shop_open = not shop_open
                            if shop_open:
                                item_shop_open = False
                    if event.key == pygame.K_n and player.is_alive():
                        if not paused:
                            item_shop_open = not item_shop_open
                            if item_shop_open:
                                shop_open = False
                    # pause menu shortcuts
                    if paused:
                        if event.key in (pygame.K_p, pygame.K_ESCAPE):
                            paused = False
                        elif event.key == pygame.K_r:
                            # restart match
                            save_state()
                            running = False
                        elif event.key == pygame.K_q:
                            save_state()
                            pygame.quit()
                            sys.exit(0)
                    if shop_open:
                        costs = compute_costs()
                        # покупки 1..6
                        if event.key in (pygame.K_1, pygame.K_KP1):
                            cost = costs["speed_cost"]
                            if cost > 0 and player.coins >= cost:
                                player.coins -= cost
                                speed_levels += 1
                                player.speed_multiplier *= 1.12
                                save_state()
                        if event.key in (pygame.K_2, pygame.K_KP2):
                            cost = costs["firerate_cost"]
                            if cost > 0 and player.coins >= cost:
                                player.coins -= cost
                                firerate_levels += 1
                                player.fire_rate_multiplier *= 1.15
                                save_state()
                        if event.key in (pygame.K_3, pygame.K_KP3):
                            cost = costs["pierce_cost"]
                            if cost > 0 and player.coins >= cost:
                                player.coins -= cost
                                pierce_levels += 1
                                player.bullet_pierce_level += 1
                                save_state()
                        if event.key in (pygame.K_4, pygame.K_KP4):
                            cost = costs["size_cost"]
                            if cost > 0 and player.coins >= cost:
                                player.coins -= cost
                                size_levels += 1
                                player.bullet_size_level += 1
                                save_state()
                        if event.key in (pygame.K_5, pygame.K_KP5):
                            cost = costs["magnet_cost"]
                            if cost > 0 and player.coins >= cost:
                                player.coins -= cost
                                magnet_levels += 1
                                player.magnet_radius += 60.0
                                save_state()
                        if event.key in (pygame.K_6, pygame.K_KP6):
                            cost = costs["hp_cost"]
                            if cost > 0 and player.coins >= cost:
                                player.coins -= cost
                                hp_levels += 1
                                player.max_health_bonus += 1
                                player.health = min(player.max_health(), player.health + 1)
                                save_state()
                        # page switch
                        if event.key == pygame.K_LEFT:
                            shop_page = 0
                        if event.key == pygame.K_RIGHT:
                            shop_page = 1
                        # page 2 purchases
                        if shop_page == 1:
                            if event.key in (pygame.K_7, pygame.K_KP7):
                                cost = costs["dmg_cost"]
                                if cost > 0 and player.coins >= cost:
                                    player.coins -= cost
                                    player.bullet_damage_level += 1
                                    save_state()
                            if event.key in (pygame.K_8, pygame.K_KP8):
                                cost = costs["coin_cost"]
                                if cost > 0 and player.coins >= cost:
                                    player.coins -= cost
                                    player.coin_gain_level += 1
                                    save_state()
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and shop_open:
                    # Click to buy
                    costs = compute_costs()
                    btns = draw_shop(screen, big_font, font, player, costs, speed_levels, firerate_levels, shop_page)  # to get rects for current frame
                    mx, my = pygame.mouse.get_pos()
                    for idx, rect in enumerate(btns):
                        if rect.collidepoint((mx, my)):
                            if idx == 0:
                                cost = costs["speed_cost"]
                                if cost > 0 and player.coins >= cost:
                                    player.coins -= cost
                                    speed_levels += 1
                                    player.speed_multiplier *= 1.12
                                    save_state()
                            elif idx == 1:
                                cost = costs["firerate_cost"]
                                if cost > 0 and player.coins >= cost:
                                    player.coins -= cost
                                    firerate_levels += 1
                                    player.fire_rate_multiplier *= 1.15
                                    save_state()
                            elif idx == 2:
                                cost = costs["pierce_cost"]
                                if cost > 0 and player.coins >= cost:
                                    player.coins -= cost
                                    pierce_levels += 1
                                    player.bullet_pierce_level += 1
                                    save_state()
                            elif idx == 3:
                                cost = costs["size_cost"]
                                if cost > 0 and player.coins >= cost:
                                    player.coins -= cost
                                    size_levels += 1
                                    player.bullet_size_level += 1
                                    save_state()
                            elif idx == 4:
                                cost = costs["magnet_cost"]
                                if cost > 0 and player.coins >= cost:
                                    player.coins -= cost
                                    magnet_levels += 1
                                    player.magnet_radius += 60.0
                                    save_state()
                            elif idx == 5 and shop_page == 0:
                                cost = costs["hp_cost"]
                                if cost > 0 and player.coins >= cost:
                                    player.coins -= cost
                                    hp_levels += 1
                                    player.max_health_bonus += 1
                                    player.health = min(player.max_health(), player.health + 1)
                                    save_state()
                            # page 2 (only two rows)
                            elif shop_page == 1 and idx == 0:
                                cost = costs["dmg_cost"]
                                if cost > 0 and player.coins >= cost:
                                    player.coins -= cost
                                    player.bullet_damage_level += 1
                                    save_state()
                            elif shop_page == 1 and idx == 1:
                                cost = costs["coin_cost"]
                                if cost > 0 and player.coins >= cost:
                                    player.coins -= cost
                                    player.coin_gain_level += 1
                                    save_state()

            keys = pygame.key.get_pressed()
            mouse_pos = Vector2(pygame.mouse.get_pos())
            mouse_pressed = pygame.mouse.get_pressed()[0]

            # Update
            if not paused and not shop_open and not item_shop_open and not console_open and not admin_panel_open and player.is_alive():
                player.update(dt, keys)
                if mouse_pressed:
                    bullet = player.try_shoot(mouse_pos)
                    if bullet:
                        bullets.append(bullet)

            # Update bullets
            for b in bullets:
                b.update(dt)
            bullets = [b for b in bullets if b.is_alive()]
            
            # Update enemy bullets
            for eb in enemy_bullets:
                eb.update(dt)
            enemy_bullets = [eb for eb in enemy_bullets if eb.is_alive()]

            # Update enemies and spawner
            if not paused and not shop_open and not item_shop_open and not console_open and not admin_panel_open and player.is_alive():
                spawner.update(dt)
                if spawner.timer <= 0:
                    enemies.append(spawner.spawn_enemy())
                    spawner.timer = spawner.current_interval

                for e in enemies:
                    e.update(dt, player.position)
                    if isinstance(e, ShooterEnemy) and e.ready_to_shoot():
                        dir_vec = (player.position - e.position)
                        if dir_vec.length_squared() > 1e-6:
                            v = dir_vec.normalize() * (220 + 6 * spawner.level)
                            enemy_bullets.append(EnemyBullet(position=Vector2(e.position), velocity=v))
                            e.reset_shoot()

            # coins update
            for c in coins:
                c.update(dt, player.position, player.magnet_radius)
            
            # Update explosions
            for exp in explosions:
                exp.update(dt)
            explosions = [exp for exp in explosions if exp.is_alive()]

            # Collisions: bullets vs enemies
            if not paused and not shop_open and not item_shop_open and not console_open and not admin_panel_open and player.is_alive():
                alive_enemies: list[Enemy] = []
                for e in enemies:
                    hit = False
                    dead = False
                    for b in bullets:
                        if circle_intersects_circle(e.position, e.radius, b.position, b.radius):
                            hit = True
                            # damage enemy (supports bosses)
                            e.health -= 1
                            if e.health <= 0:
                                dead = True
                                score += 1
                                # Call player.on_kill() for lifesteal
                                player.on_kill()
                                # AOE explosion on kill
                                if player.aoe_on_kill_level > 0:
                                    explosion_radius = 40 + 10 * player.aoe_on_kill_level
                                    explosions.append(Explosion(
                                        position=Vector2(e.position),
                                        radius=0,
                                        max_radius=explosion_radius,
                                        damage=1 + player.aoe_on_kill_level,
                                        lifetime=0.3
                                    ))
                                # coin drop (reduced chance for normal; guaranteed bundle for boss)
                                if e.is_boss:
                                    # boss
                                    for _ in range(14):
                                        coins.append(Coin(position=Vector2(e.position), value=2, velocity=Vector2(random.uniform(-180, 180), random.uniform(-180, 180))))
                                    spawner.on_boss_killed()
                                    # small chance to drop armor
                                    if random.random() < 0.5:
                                        player.armor += 1
                                else:
                                    if random.random() < NORMAL_DROP_CHANCE:
                                        coin_value = 1 if random.random() < 0.85 else 2
                                        coins.append(Coin(position=Vector2(e.position), value=coin_value, velocity=Vector2(random.uniform(-40, 40), random.uniform(-40, 40))))
                                spawner.kills_this_level += 1
                                # consume bullet on kill unless it still has pierce
                                if b.pierce_remaining > 0:
                                    b.pierce_remaining -= 1
                                else:
                                    b.lifetime = 0.0
                                break
                            # handle bullet pierce when not killing
                            if b.pierce_remaining > 0:
                                b.pierce_remaining -= 1
                            else:
                                b.lifetime = 0.0
                            break
                    if not dead:
                        alive_enemies.append(e)
                enemies = alive_enemies
                bullets = [b for b in bullets if b.is_alive()]

                # Spawn boss when ready
                if spawner.should_spawn_boss():
                    enemies.append(spawner.spawn_boss(player.position))

            # Collisions: enemies vs player
            if not paused and not shop_open and not item_shop_open and not console_open and not admin_panel_open and player.is_alive():
                for e in enemies:
                    if circle_intersects_circle(player.position, player.radius, e.position, e.radius):
                        player.take_hit()
                        to_enemy = (e.position - player.position)
                        if to_enemy.length_squared() > 0:
                            e.position += to_enemy.normalize() * 12
            # Collisions: enemy bullets vs player
            if not paused and not shop_open and not item_shop_open and not console_open and not admin_panel_open and player.is_alive():
                remaining_eb: list[EnemyBullet] = []
                for eb in enemy_bullets:
                    if circle_intersects_circle(player.position, player.radius, eb.position, eb.radius):
                        player.take_hit()
                    else:
                        remaining_eb.append(eb)
                enemy_bullets = remaining_eb

            # Pickup coins
            if not paused and not shop_open and not item_shop_open and not console_open and not admin_panel_open and player.is_alive():
                remaining_coins: list[Coin] = []
                picked_any = False
                for c in coins:
                    if circle_intersects_circle(player.position, player.radius + 4, c.position, c.radius):
                        player.coins += c.value
                        picked_any = True
                    else:
                        remaining_coins.append(c)
                coins = remaining_coins
                if picked_any:
                    # autosave coins progress
                    save_state()

            # Render
            screen.fill(BACKGROUND_COLOR)
            for b in bullets:
                b.draw(screen)
            for e in enemies:
                e.draw(screen)
            for c in coins:
                c.draw(screen)
            for eb in enemy_bullets:
                eb.draw(screen)
            for exp in explosions:
                exp.draw(screen)
            player.draw(screen, mouse_pos)
            draw_ui(screen, font, score, player)
            # show level
            level_text = font.render(f"Level {spawner.level}", True, UI_ACCENT)
            screen.blit(level_text, (14, 58))
            draw_level_progress(screen, font, spawner)

            # Shop overlay
            if shop_open:
                # shop pagination: left/right keys to change page
                if pygame.key.get_pressed()[pygame.K_LEFT]:
                    shop_page = 0
                if pygame.key.get_pressed()[pygame.K_RIGHT]:
                    shop_page = 1
                draw_shop(screen, big_font, font, player, compute_costs(), speed_levels, firerate_levels, shop_page)
            # Item shop overlay (second shop)
            # Console overlay
            if console_open:
                draw_console(screen, font, console_text, console_history)
            
            # Admin panel overlay
            if admin_panel_open:
                draw_admin_panel(screen, font, admin_input, admin_authenticated)
            
            if item_shop_open:
                overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 200))
                screen.blit(overlay, (0, 0))
                panel_w, panel_h = 720, 420
                panel_rect = pygame.Rect((WINDOW_WIDTH - panel_w) // 2, (WINDOW_HEIGHT - panel_h) // 2, panel_w, panel_h)
                pygame.draw.rect(screen, (32, 36, 42), panel_rect, border_radius=10)
                pygame.draw.rect(screen, (80, 86, 96), panel_rect, 2, border_radius=10)
                title = big_font.render("МАГАЗИН ПРЕДМЕТОВ (N)", True, UI_ACCENT)
                screen.blit(title, title.get_rect(midtop=(panel_rect.centerx, panel_rect.top + 18)))
                # items (10 entries)
                items2 = [
                    ("Q) Уворот", player.dodge_level, "+5% шанс уклонения", 16),
                    ("W) Реген", player.regen_level, "реген + быстрее", 20),
                    ("E) Вампиризм", player.lifesteal_level, "+1 HP раз в N убийств", 28),
                    ("R) Крит", player.crit_level, "+крит шанс/урон", 24),
                    ("T) Взрыв при убийстве", player.aoe_on_kill_level, "AOE урон при смерти врага", 30),
                    ("Y) Магнит+", player.magnet_bonus_level, "+20px радиуса", 12),
                    ("U) Скорость пули", player.bullet_speed_level, "+8%", 14),
                    ("I) Броня+", player.armor, "+1 броня", 22),
                    ("O) Лечение", 0, "+1 HP (мгновенно)", 18),
                    ("P) Сундук", 0, "рандомный бонус", 26),
                ]
                # layout grid 2 columns
                btns2: list[tuple[pygame.Rect, str]] = []
                y = panel_rect.top + 80
                for idx, (label, level, desc, base_cost) in enumerate(items2):
                    col = idx % 2
                    row = idx // 2
                    x = panel_rect.left + 24 + col * ((panel_w - 48) // 2)
                    w = (panel_w - 72) // 2
                    r = pygame.Rect(x, y + row * 62, w, 52)
                    # scale cost by level
                    lvl = level if isinstance(level, int) else 0
                    cost = int(base_cost * (1 + 0.5 * lvl))
                    afford = player.coins >= cost
                    bg = (46, 52, 60) if afford else (36, 40, 46)
                    if r.collidepoint(pygame.mouse.get_pos()):
                        bg = (56, 62, 70) if afford else (44, 48, 54)
                    pygame.draw.rect(screen, bg, r, border_radius=8)
                    pygame.draw.rect(screen, (120, 130, 140), r, 2, border_radius=8)
                    screen.blit(font.render(label, True, (230,230,240)), (r.left+10, r.top+6))
                    screen.blit(font.render(f"Уровень: {level}", True, UI_ACCENT), (r.left+10, r.top+26))
                    screen.blit(font.render(desc, True, (200,200,210)), (r.left+160, r.top+6))
                    screen.blit(font.render(f"Цена: {cost}", True, COIN_COLOR), (r.right-120, r.top+16))
                    btns2.append((r, label[0]))
                # handle clicks (debounced)
                mouse_down = pygame.mouse.get_pressed()[0]
                if mouse_down and not item_click_block:
                    mx,my = pygame.mouse.get_pos()
                    for rect, keychar in btns2:
                        if rect.collidepoint((mx,my)):
                            kc = keychar
                            if kc == 'Q' and player.coins >= int(16 * (1 + 0.5 * player.dodge_level)):
                                player.coins -= int(16 * (1 + 0.5 * player.dodge_level)); player.dodge_level += 1
                            elif kc == 'W' and player.coins >= int(20 * (1 + 0.5 * player.regen_level)):
                                player.coins -= int(20 * (1 + 0.5 * player.regen_level)); player.regen_level += 1
                            elif kc == 'E' and player.coins >= int(28 * (1 + 0.5 * player.lifesteal_level)):
                                player.coins -= int(28 * (1 + 0.5 * player.lifesteal_level)); player.lifesteal_level += 1
                            elif kc == 'R' and player.coins >= int(24 * (1 + 0.5 * player.crit_level)):
                                player.coins -= int(24 * (1 + 0.5 * player.crit_level)); player.crit_level += 1
                            elif kc == 'T' and player.coins >= int(30 * (1 + 0.5 * player.aoe_on_kill_level)):
                                player.coins -= int(30 * (1 + 0.5 * player.aoe_on_kill_level)); player.aoe_on_kill_level += 1
                            elif kc == 'Y' and player.coins >= int(12 * (1 + 0.5 * player.magnet_bonus_level)):
                                player.coins -= int(12 * (1 + 0.5 * player.magnet_bonus_level)); player.magnet_bonus_level += 1; player.magnet_radius += 20
                            elif kc == 'U' and player.coins >= int(14 * (1 + 0.5 * player.bullet_speed_level)):
                                player.coins -= int(14 * (1 + 0.5 * player.bullet_speed_level)); player.bullet_speed_level += 1
                            elif kc == 'I' and player.coins >= 22:
                                player.coins -= 22; player.armor += 1
                            elif kc == 'O' and player.coins >= 18:
                                player.coins -= 18; player.health = min(player.max_health(), player.health + 1)
                            elif kc == 'P' and player.coins >= 26:
                                player.coins -= 26; choice = random.choice(['armor','heal','dmg','coins']);
                                if choice == 'armor': player.armor += 1
                                elif choice == 'heal': player.health = min(player.max_health(), player.health + 1)
                                elif choice == 'dmg': player.bullet_damage_level += 1
                                else: player.coins += random.randint(5,12)
                            save_state()
                            break
                    item_click_block = True
                if not mouse_down:
                    item_click_block = False
            # Pause overlay
            if paused:
                overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 160))
                screen.blit(overlay, (0, 0))
                title = big_font.render("ПАУЗА", True, UI_ACCENT)
                trect = title.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 - 40))
                screen.blit(title, trect)
                hint1 = font.render("ESC/P — продолжить", True, TEXT_COLOR)
                hint2 = font.render("R — перезапуск", True, TEXT_COLOR)
                hint3 = font.render("Q — выход", True, TEXT_COLOR)
                screen.blit(hint1, hint1.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 10)))
                screen.blit(hint2, hint2.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 34)))
                screen.blit(hint3, hint3.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 58)))
            # Level/Boss intros and transitions
            if spawner.boss_active and spawner.boss_banner_timer > 0:
                spawner.boss_banner_timer -= dt
                overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 120))
                screen.blit(overlay, (0, 0))
                msg = big_font.render("БОСС", True, (255, 150, 150))
                rect = msg.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2))
                screen.blit(msg, rect)
            if spawner.level_transition_timer > 0:
                overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 120))
                screen.blit(overlay, (0, 0))
                lvl_msg = big_font.render(f"Уровень {spawner.level}", True, UI_ACCENT)
                lvl_rect = lvl_msg.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2))
                screen.blit(lvl_msg, lvl_rect)

            if not player.is_alive():
                game_over_screen(screen, big_font, font, score)

            pygame.display.flip()

            # Restart/Exit when dead
            if not player.is_alive():
                keys = pygame.key.get_pressed()
                if keys[pygame.K_r]:
                    # save on restart
                    save_state()
                    running = False  # break inner loop, restart new match


if __name__ == "__main__":
    run()


