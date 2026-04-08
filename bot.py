import discord
from discord.ext import commands
import re
import os
import random
from typing import Optional, List

# ─── Configuração ────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN")
ROLE_PREFIX = "Membro"
ROLE_COLOR = discord.Color.blurple()
INVITE_LINK = "https://discord.gg/m3BtpBhcy6"
OWNER_ID = 308987924559691788  # Único usuário autorizado a usar !sortear

# ─── Setup do bot ────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ─── Funções auxiliares ───────────────────────────────────────────────────────

def parse_role_number(role: discord.Role) -> Optional[int]:
    pattern = rf"^{re.escape(ROLE_PREFIX)}\s+(\d+)$"
    match = re.match(pattern, role.name, re.IGNORECASE)
    return int(match.group(1)) if match else None


def get_managed_roles(guild: discord.Guild) -> List[discord.Role]:
    managed = []
    for role in guild.roles:
        num = parse_role_number(role)
        if num is not None:
            managed.append((num, role))
    managed.sort(key=lambda x: x[0])
    return [role for _, role in managed]


async def find_empty_role(roles: List[discord.Role]) -> Optional[discord.Role]:
    for role in roles:
        if len(role.members) == 0:
            return role
    return None


async def create_next_role(guild: discord.Guild, roles: List[discord.Role]) -> discord.Role:
    if roles:
        last_num = parse_role_number(roles[-1])
        next_num = last_num + 1
        position = max(roles[-1].position - 1, 1)
    else:
        next_num = 1
        position = 1

    new_role_name = f"{ROLE_PREFIX} {next_num}"
    new_role = await guild.create_role(
        name=new_role_name,
        color=ROLE_COLOR,
        reason="Criado automaticamente pelo bot de boas-vindas",
    )

    try:
        await new_role.edit(position=position)
    except discord.HTTPException:
        pass

    print(f"[Bot] Cargo criado: '{new_role_name}'")
    return new_role


async def send_invite(user: discord.User, motivo: str):
    try:
        await user.send(
            f"👋 Olá, **{user.display_name}**!\n\n"
            f"Você **{motivo}** do servidor.\n"
            f"Se quiser voltar, use o convite abaixo:\n\n"
            f"🔗 {INVITE_LINK}"
        )
        print(f"[Bot] Convite enviado para {user.display_name} ({motivo})")
    except discord.Forbidden:
        print(f"[Bot] Não foi possível enviar DM para {user.display_name} (DMs fechadas)")


# ─── Evento: membro entra no servidor ────────────────────────────────────────

@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    print(f"[Bot] {member.display_name} entrou em '{guild.name}'")

    managed_roles = get_managed_roles(guild)
    target_role = await find_empty_role(managed_roles)

    if target_role is None:
        target_role = await create_next_role(guild, managed_roles)

    await member.add_roles(target_role, reason="Cargo automático de boas-vindas")
    print(f"[Bot] Cargo '{target_role.name}' atribuído a {member.display_name}")


# ─── Evento: membro saiu ou foi expulso ──────────────────────────────────────

@bot.event
async def on_member_remove(member: discord.Member):
    try:
        await member.guild.fetch_ban(member)
        return
    except discord.NotFound:
        pass
    await send_invite(member, "saiu ou foi expulso")


# ─── Evento: membro foi banido ────────────────────────────────────────────────

@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    await send_invite(user, "foi banido")


# ─── Comando: listar cargos ───────────────────────────────────────────────────

@bot.command(name="cargos")
@commands.has_permissions(manage_roles=True)
async def listar_cargos(ctx: commands.Context):
    roles = get_managed_roles(ctx.guild)
    if not roles:
        await ctx.send("Nenhum cargo gerenciado encontrado.")
        return

    lines = []
    for role in roles:
        members = ", ".join(m.display_name for m in role.members) or "*(vazio)*"
        lines.append(f"**{role.name}** → {members}")

    await ctx.send("\n".join(lines))


# ─── Comando: sortear cargos ─────────────────────────────────────────────────

@bot.command(name="sortear")
@commands.check(lambda ctx: ctx.author.id == 308987924559691788)
@commands.has_permissions(manage_roles=True)
@commands.cooldown(1, 10, commands.BucketType.guild)  # Evita duplo disparo
async def sortear_cargos(ctx: commands.Context):
    guild = ctx.guild
    await ctx.send("🔀 Sorteando cargos, aguarde...")

    # 1. Pega todos os cargos gerenciados
    managed_roles = get_managed_roles(guild)
    managed_role_ids = {r.id for r in managed_roles}

    # 2. Coleta membros que possuem qualquer cargo gerenciado (sem duplicatas)
    members_with_roles = []
    seen_ids = set()
    for role in managed_roles:
        for member in role.members:
            if member.id not in seen_ids:
                members_with_roles.append(member)
                seen_ids.add(member.id)

    if not members_with_roles:
        await ctx.send("❌ Nenhum membro com cargos gerenciados encontrado.")
        return

    # 3. Remove TODOS os cargos gerenciados de TODOS os membros envolvidos
    for member in members_with_roles:
        roles_to_remove = [r for r in member.roles if r.id in managed_role_ids]
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="Sorteio: limpando cargos antigos")

    # 4. Embaralha os membros
    random.shuffle(members_with_roles)

    # 5. Garante cargos suficientes
    managed_roles = get_managed_roles(guild)  # Recarrega após possíveis criações
    while len(managed_roles) < len(members_with_roles):
        new_role = await create_next_role(guild, managed_roles)
        managed_roles.append(new_role)

    # 6. Atribui 1 cargo por membro na nova ordem
    lines = ["🎲 **Nova hierarquia de cargos atualizada.** @everyone\n"]
    for i, member in enumerate(members_with_roles):
        role = managed_roles[i]
        await member.add_roles(role, reason="Sorteio de cargos")
        lines.append(f"**{role.name}:** {member.display_name}")
        print(f"[Bot] Sorteio: {member.display_name} → {role.name}")

    await ctx.send("\n".join(lines))
    print(f"[Bot] Sorteio concluído para {len(members_with_roles)} membros.")


# ─── Inicialização ────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"[Bot] Conectado como {bot.user} (ID: {bot.user.id})")
    print(f"[Bot] Prefixo dos cargos: '{ROLE_PREFIX} N'")


bot.run(TOKEN)
