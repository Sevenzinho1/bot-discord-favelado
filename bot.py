import discord
from discord.ext import commands
import re
from typing import Optional, List

# ─── Configuração ────────────────────────────────────────────────────────────
TOKEN = "MTQ4OTQyNzY1NTYyMjM5NDA1MA.GljEm8.SBCkkRwk791tQDBB8WNutSwz2CP-T-xGDTw2-U"
ROLE_PREFIX = "Membro"                 # Prefixo dos cargos: Membro 1, Membro 2 …
ROLE_COLOR = discord.Color.blurple()   # Cor dos cargos criados automaticamente
INVITE_LINK = "https://discord.gg/m3BtpBhcy6"  # Link de convite do servidor

# ─── Setup do bot ────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ─── Funções auxiliares ───────────────────────────────────────────────────────

def parse_role_number(role: discord.Role) -> Optional[int]:
    """Retorna o número do cargo se o nome seguir o padrão 'Prefixo N', senão None."""
    pattern = rf"^{re.escape(ROLE_PREFIX)}\s+(\d+)$"
    match = re.match(pattern, role.name, re.IGNORECASE)
    return int(match.group(1)) if match else None


def get_managed_roles(guild: discord.Guild) -> List[discord.Role]:
    """Retorna os cargos gerenciados pelo bot, ordenados pelo número crescente."""
    managed = []
    for role in guild.roles:
        num = parse_role_number(role)
        if num is not None:
            managed.append((num, role))
    managed.sort(key=lambda x: x[0])
    return [role for _, role in managed]


async def find_empty_role(roles: List[discord.Role]) -> Optional[discord.Role]:
    """Retorna o primeiro cargo (menor número) que não possui nenhum membro."""
    for role in roles:
        if len(role.members) == 0:
            return role
    return None


async def create_next_role(guild: discord.Guild, roles: List[discord.Role]) -> discord.Role:
    """Cria o próximo cargo na sequência numérica."""
    if roles:
        last_num = parse_role_number(roles[-1])
        next_num = last_num + 1
    else:
        next_num = 1

    new_role_name = f"{ROLE_PREFIX} {next_num}"
    new_role = await guild.create_role(
        name=new_role_name,
        color=ROLE_COLOR,
        reason="Criado automaticamente pelo bot de boas-vindas",
    )
    print(f"[Bot] Cargo criado: '{new_role_name}'")
    return new_role


async def send_invite(user: discord.User, motivo: str):
    """Envia o link de convite via DM para o usuário."""
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


# ─── Evento: membro saiu voluntariamente ou foi expulso ──────────────────────

@bot.event
async def on_member_remove(member: discord.Member):
    # Verifica se foi um ban (para não mandar DM duplicada)
    try:
        await member.guild.fetch_ban(member)
        return  # É um ban, o on_member_ban já vai lidar
    except discord.NotFound:
        pass  # Não é ban: saiu voluntariamente ou foi expulso

    await send_invite(member, "saiu ou foi expulso")


# ─── Evento: membro foi banido ────────────────────────────────────────────────

@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    await send_invite(user, "foi banido")


# ─── Comando de diagnóstico (opcional) ───────────────────────────────────────

@bot.command(name="cargos")
@commands.has_permissions(manage_roles=True)
async def listar_cargos(ctx: commands.Context):
    """Lista os cargos gerenciados e seus membros atuais."""
    roles = get_managed_roles(ctx.guild)
    if not roles:
        await ctx.send("Nenhum cargo gerenciado encontrado.")
        return

    lines = []
    for role in roles:
        members = ", ".join(m.display_name for m in role.members) or "*(vazio)*"
        lines.append(f"**{role.name}** → {members}")

    await ctx.send("\n".join(lines))


# ─── Inicialização ────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"[Bot] Conectado como {bot.user} (ID: {bot.user.id})")
    print(f"[Bot] Prefixo dos cargos: '{ROLE_PREFIX} N'")


bot.run(TOKEN)
