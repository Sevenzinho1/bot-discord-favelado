import discord
from discord.ext import commands
import re
import os
import random
import asyncio
import json
from datetime import datetime
import zoneinfo
import pytz
from typing import Optional, List

# ─── Configuração ────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN")
ROLE_PREFIX = "Membro"
ROLE_COLOR = discord.Color.blurple()
INVITE_LINK = "https://discord.gg/m3BtpBhcy6"
OWNER_ID = 308987924559691788
LOG_CHANNEL = "banidos"
SORTEAR_CHANNEL = "geral"
SORTEAR_MIN_SECONDS = 3600
SORTEAR_MAX_SECONDS = 115200
AUDIO_FILE = "audio_banimento.mp3"
ALERT_MEMBER_ID = 501493721595117571
STATS_FILE = "/app/data/kick_ban_stats.json"
os.makedirs("/app/data", exist_ok=True)

# Tung Bot config
IMAGEM_TUNG = os.environ.get("IMAGEM_TUNG", "")
IMAGEM_TUNG_DARK = "https://i.imgur.com/p4PNbgT.jpg"

# Rastreia quem baniu/expulsou nesta estadia
executores_punicao: set = set()


# ─── Setup do bot ────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.moderation = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ─── Funções auxiliares de cargo ─────────────────────────────────────────────

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


async def reajustar_hierarquia(guild: discord.Guild, numero_saiu: int):
    managed_roles = get_managed_roles(guild)
    roles_abaixo = [r for r in managed_roles if parse_role_number(r) > numero_saiu]

    for role in roles_abaixo:
        num = parse_role_number(role)
        cargo_anterior = next((r for r in managed_roles if parse_role_number(r) == num - 1), None)
        if cargo_anterior is None:
            continue
        for member in list(role.members):
            await member.remove_roles(role, reason="Reajuste de hierarquia após saída")
            await member.add_roles(cargo_anterior, reason="Reajuste de hierarquia após saída")
            print(f"[Bot] {member.display_name}: {role.name} → {cargo_anterior.name}")


# ─── Funções auxiliares de log ────────────────────────────────────────────────

def get_log_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    return discord.utils.get(guild.text_channels, name=LOG_CHANNEL)


def get_sortear_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    return discord.utils.get(guild.text_channels, name=SORTEAR_CHANNEL)


def hora_agora() -> str:
    tz = zoneinfo.ZoneInfo("America/Sao_Paulo")
    return datetime.now(tz).strftime("%d/%m/%Y às %H:%M")


def horario_brasilia() -> str:
    tz = pytz.timezone("America/Sao_Paulo")
    return datetime.now(tz).strftime("%d/%m/%Y às %H:%M:%S")


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


# ─── Tung Bot: embeds de saída ───────────────────────────────────────────────

async def enviar_embed_tung(canal: discord.TextChannel, usuario: discord.User, tipo: str):
    """Embed dourado padrão."""
    embed = discord.Embed(
        title=f"**{usuario.name} is with Tung now.**",
        color=0xF0E6C8,
    )
    if IMAGEM_TUNG:
        embed.set_image(url=IMAGEM_TUNG)
    embed.set_thumbnail(url=usuario.display_avatar.url)
    embed.add_field(name="👤 Usuário", value=usuario.name, inline=True)
    embed.add_field(name="📋 Evento", value=tipo, inline=True)
    embed.add_field(name="🕐 Horário (Brasília)", value=horario_brasilia(), inline=False)
    embed.set_footer(text="See you on the other side 🪽")
    await canal.send(embeds=[embed])


async def enviar_embed_tung_dark(canal: discord.TextChannel, usuario: discord.User, tipo: str):
    """Embed sinistra vermelha — para quem puniu alguém."""
    embed = discord.Embed(
        title=f"**{usuario.name} iS wITh tUng nOW.**",
        color=0x8B0000,
    )
    embed.set_image(url=IMAGEM_TUNG_DARK)
    embed.set_thumbnail(url=usuario.display_avatar.url)
    embed.add_field(name="😈 Usuário", value=usuario.name, inline=True)
    embed.add_field(name="🩸 Evento", value=tipo, inline=True)
    embed.add_field(name="🕯️ Horário (Brasília)", value=horario_brasilia(), inline=False)
    embed.set_footer(text="We'll meet where the light doesn't reach. 🔥")
    await canal.send(embeds=[embed])


async def processar_saida_tung(guild: discord.Guild, usuario: discord.User, tipo: str):
    # Embeds do Tung vão para o #geral, com fallback para qualquer canal disponível
    canal = get_sortear_channel(guild)
    if not canal:
        # Último recurso: qualquer canal de texto que o bot possa enviar
        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages:
                canal = ch
                break
    if not canal:
        print(f"[Bot] Nenhum canal encontrado para embed Tung!")
        return

    print(f"[Bot] Enviando embed Tung para {usuario.name} no canal #{canal.name} (executor_punicao: {usuario.id in executores_punicao})")

    if usuario.id in executores_punicao:
        await enviar_embed_tung_dark(canal, usuario, tipo)
    else:
        await enviar_embed_tung(canal, usuario, tipo)

    executores_punicao.discard(usuario.id)


# ─── Função: tocar áudio ─────────────────────────────────────────────────────

async def tocar_audio(guild: discord.Guild, arquivo: str, maior_call: bool = False):
    """Entra na call (maior se maior_call=True, senão primeira), toca o áudio e sai."""
    voice_channel = None
    if maior_call:
        max_members = 0
        for vc in guild.voice_channels:
            if len(vc.members) > max_members:
                max_members = len(vc.members)
                voice_channel = vc
    else:
        for vc in guild.voice_channels:
            if len(vc.members) > 0:
                voice_channel = vc
                break

    if voice_channel is None:
        print("[Bot] Nenhuma call ativa encontrada.")
        return

    voice_client = None
    try:
        voice_client = await voice_channel.connect()
        print(f"[Bot] Entrou na call: {voice_channel.name}")

        from pydub import AudioSegment
        import io
        audio = AudioSegment.from_mp3(arquivo)
        audio = audio.set_frame_rate(48000).set_channels(2).set_sample_width(2)
        audio_source = discord.PCMAudio(io.BytesIO(audio.raw_data))
        voice_client.play(audio_source)

        while voice_client.is_playing():
            await asyncio.sleep(1)

        await voice_client.disconnect()
        print("[Bot] Saiu da call.")
    except Exception as e:
        print(f"[Bot] Erro ao tocar áudio: {e}")
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()


# ─── Funções de estatísticas ─────────────────────────────────────────────────

def load_stats() -> dict:
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_stats(stats: dict):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)


def increment_stat(executor_id: int, executor_name: str, victim_id: int = None, victim_name: str = None):
    stats = load_stats()
    key = str(executor_id)
    if key not in stats:
        stats[key] = {"name": executor_name, "count": 0, "received": 0}
    stats[key]["count"] += 1
    stats[key]["name"] = executor_name

    if victim_id is not None:
        vkey = str(victim_id)
        if vkey not in stats:
            stats[vkey] = {"name": victim_name, "count": 0, "received": 0}
        if "received" not in stats[vkey]:
            stats[vkey]["received"] = 0
        stats[vkey]["received"] += 1
        stats[vkey]["name"] = victim_name

    save_stats(stats)


async def scan_audit_log(guild: discord.Guild):
    stats = load_stats()
    for v in stats.values():
        if "count" not in v:
            v["count"] = 0
        if "received" not in v:
            v["received"] = 0

    actions = [discord.AuditLogAction.ban, discord.AuditLogAction.kick]
    for action in actions:
        try:
            last_id = None
            while True:
                entries = []
                kwargs = {"limit": 100, "action": action}
                if last_id:
                    kwargs["before"] = discord.Object(id=last_id)
                async for entry in guild.audit_logs(**kwargs):
                    entries.append(entry)
                    key = str(entry.user.id)
                    if key not in stats:
                        stats[key] = {"name": entry.user.display_name, "count": 0, "received": 0}
                    stats[key]["count"] += 1
                    stats[key]["name"] = entry.user.display_name
                    vkey = str(entry.target.id)
                    if vkey not in stats:
                        stats[vkey] = {"name": str(entry.target), "count": 0, "received": 0}
                    stats[vkey]["received"] += 1
                if len(entries) < 100:
                    break
                last_id = entries[-1].id
        except discord.Forbidden:
            pass

    save_stats(stats)
    total = sum(v.get("count", 0) for v in stats.values())
    print(f"[Bot] Audit log escaneado: {total} ações registradas.")


# ─── Lógica central do sorteio ───────────────────────────────────────────────

async def executar_sorteio(guild: discord.Guild, channel: discord.TextChannel):
    managed_roles = get_managed_roles(guild)
    managed_role_ids = {r.id for r in managed_roles}

    members_with_roles = []
    seen_ids = set()
    for role in managed_roles:
        for member in role.members:
            if member.id not in seen_ids:
                members_with_roles.append(member)
                seen_ids.add(member.id)

    if not members_with_roles:
        await channel.send("Nenhum membro com cargos gerenciados encontrado.")
        return

    for member in members_with_roles:
        roles_to_remove = [r for r in member.roles if r.id in managed_role_ids]
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="Sorteio: limpando cargos antigos")

    random.shuffle(members_with_roles)

    managed_roles = get_managed_roles(guild)
    while len(managed_roles) < len(members_with_roles):
        new_role = await create_next_role(guild, managed_roles)
        managed_roles.append(new_role)

    lines = ["🎲 **Nova hierarquia de cargos atualizada.**\n"]
    for i, member in enumerate(members_with_roles):
        role = managed_roles[i]
        await member.add_roles(role, reason="Sorteio de cargos")
        lines.append(f"**{role.name}:** {member.display_name}")
        print(f"[Bot] Sorteio: {member.display_name} → {role.name}")

    await channel.send("\n".join(lines))
    print(f"[Bot] Sorteio concluído para {len(members_with_roles)} membros.")


# ─── Loop automático de sorteio ──────────────────────────────────────────────

async def loop_sorteio_automatico():
    await bot.wait_until_ready()
    ultimo_intervalo = None

    while not bot.is_closed():
        alto_threshold = SORTEAR_MIN_SECONDS + (SORTEAR_MAX_SECONDS - SORTEAR_MIN_SECONDS) * 0.75

        if ultimo_intervalo is not None and ultimo_intervalo >= alto_threshold:
            intervalo = random.randint(SORTEAR_MIN_SECONDS, (SORTEAR_MIN_SECONDS + SORTEAR_MAX_SECONDS) // 2)
            print(f"[Bot] Ultimo intervalo foi alto ({ultimo_intervalo//3600}h), forcando intervalo baixo.")
        else:
            intervalo = random.randint(SORTEAR_MIN_SECONDS, SORTEAR_MAX_SECONDS)

        ultimo_intervalo = intervalo
        horas = intervalo // 3600
        minutos = (intervalo % 3600) // 60
        print(f"[Bot] Proximo sorteio automatico em {horas}h {minutos}min ({intervalo}s)")

        await asyncio.sleep(intervalo)

        print("[Bot] Disparando sorteio automatico...")
        for guild in bot.guilds:
            channel = get_sortear_channel(guild)
            if channel:
                await channel.send("Sorteando cargos automaticamente, aguarde...")
                await executar_sorteio(guild, channel)


# ─── Evento: impede atribuição manual de cargos ──────────────────────────────

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    guild = after.guild
    managed_roles = get_managed_roles(guild)
    managed_role_ids = {r.id: r for r in managed_roles}

    roles_added = set(after.roles) - set(before.roles)
    roles_removed = set(before.roles) - set(after.roles)

    for role in roles_added:
        if role.id not in managed_role_ids:
            continue
        try:
            async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.member_role_update):
                if entry.target.id == after.id:
                    if entry.user.id == bot.user.id:
                        return
                    await after.remove_roles(role, reason="Atribuição manual bloqueada pelo bot")
                    print(f"[Bot] Cargo '{role.name}' removido de {after.display_name} (atribuição manual bloqueada)")
                    return
        except discord.Forbidden:
            pass

    for role in roles_removed:
        if role.id not in managed_role_ids:
            continue
        try:
            async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.member_role_update):
                if entry.target.id == after.id:
                    if entry.user.id == bot.user.id:
                        return
                    await after.add_roles(role, reason="Remoção manual bloqueada pelo bot")
                    print(f"[Bot] Cargo '{role.name}' restaurado em {after.display_name} (remoção manual bloqueada)")
                    return
        except discord.Forbidden:
            pass


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

    channel = get_log_channel(guild)
    if channel:
        embed = discord.Embed(
            description=f"**{member.display_name}**! Voltou a vida.",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID: {member.id} • {hora_agora()}")
        await channel.send(embed=embed)


# ─── Evento: membro saiu ou foi expulso ──────────────────────────────────────

@bot.event
async def on_member_remove(member: discord.Member):
    guild = member.guild
    await asyncio.sleep(1.5)

    # Verifica se foi ban
    try:
        await guild.fetch_ban(member)
        is_ban = True
    except discord.NotFound:
        is_ban = False

    # Reajusta hierarquia
    managed_roles = get_managed_roles(guild)
    managed_role_ids = {parse_role_number(r): r for r in managed_roles}
    numero_saiu = None
    for num, role in managed_role_ids.items():
        if role in member.roles:
            numero_saiu = num
            break
    if numero_saiu is not None:
        await reajustar_hierarquia(guild, numero_saiu)

    if is_ban:
        return  # on_member_ban cuida do resto

    # Verifica se foi kick
    executor_name = None
    executor_id = None
    is_kick = False
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
            if entry.target.id == member.id:
                diff = (datetime.now(pytz.utc) - entry.created_at).total_seconds()
                if diff < 10:
                    is_kick = True
                    executor_name = entry.user.display_name
                    executor_id = entry.user.id
                    executores_punicao.add(executor_id)
                break
    except discord.Forbidden:
        pass

    channel = get_log_channel(guild)

    if is_kick:
        # Embed kick no canal banidos
        variacao = random.choice(["fuzilado", "mogado"])
        embed = discord.Embed(
            description=(
                f"**{member.display_name}** Foi {variacao} por **{executor_name or 'alguém'}**\n"
                f"he's with tung now 🙏"
            ),
            color=discord.Color.orange()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID: {member.id} • {hora_agora()}")
        if channel:
            await channel.send(embed=embed)

        # Embed Tung no canal banidos
        await processar_saida_tung(guild, member, "👢 Expulso (Kick)")

        if executor_id:
            increment_stat(executor_id, executor_name, member.id, member.display_name)
        await send_invite(member, "foi expulso")
        await tocar_audio(guild, AUDIO_FILE)
    else:
        # Saída voluntária
        embed = discord.Embed(
            description=f"**{member.display_name}** saiu do servidor.",
            color=discord.Color.light_grey()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID: {member.id} • {hora_agora()}")
        if channel:
            await channel.send(embed=embed)
        await send_invite(member, "saiu")


# ─── Evento: membro foi banido ────────────────────────────────────────────────

@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    await asyncio.sleep(1.5)
    await send_invite(user, "foi banido")

    executor_name = None
    executor_id = None
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
            if entry.target.id == user.id:
                executor_name = entry.user.display_name
                executor_id = entry.user.id
                executores_punicao.add(executor_id)
                break
    except discord.Forbidden:
        pass

    if executor_id:
        increment_stat(executor_id, executor_name, user.id, user.display_name)

    channel = get_log_channel(guild)
    if channel:
        variacao = random.choice(["fuzilado", "mogado"])
        embed = discord.Embed(
            description=(
                f"**{user.display_name}** Foi {variacao} por **{executor_name or 'alguém'}**\n"
                f"he's with tung now 🙏"
            ),
            color=discord.Color.red()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"ID: {user.id} • {hora_agora()}")
        await channel.send(embed=embed)

    # Embed Tung
    await processar_saida_tung(guild, user, "🔨 Banido")
    await tocar_audio(guild, AUDIO_FILE)


# ─── Evento: responde a mensagens ────────────────────────────────────────────

FRASES_TUNG = [
    "**Você me chamou… e agora eu vejo você também.**",
    "**Eu sempre estive aqui… você só começou a perceber agora.**",
    "**Você não me invocou… apenas abriu os olhos para mim.**",
    "**Entre a luz e o silêncio… eu esperei por você.**",
    "**Ele está com Tung agora!**",
]

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Menção ao bot → frase do Tung
    if bot.user in message.mentions:
        await message.channel.send(random.choice(FRASES_TUNG))

    # Monster
    if re.findall(r'\b(monsters?|monstre)\b', message.content, re.IGNORECASE):
        await message.channel.send(file=discord.File("monster.mp4"))

    # Obrigado pela lata
    if re.search(r'\b(obrigad[oa]|brigad[oa])\b.{0,20}\b(pela|pera)\b.{0,10}\b(lata)\b', message.content, re.IGNORECASE):
        await message.channel.send("**De nada Chefe!**")

    await bot.process_commands(message)


# ─── Evento: alerta de transmissão ───────────────────────────────────────────

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.id != ALERT_MEMBER_ID:
        return

    if not before.self_stream and after.self_stream:
        voice_channel = after.channel
        if voice_channel is None:
            return
        print(f"[Bot] {member.display_name} iniciou transmissão, entrando...")
        await tocar_audio(member.guild, "audio_alerta.mp3")


# ─── Comandos ─────────────────────────────────────────────────────────────────

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


@bot.command(name="sortear")
@commands.check(lambda ctx: ctx.author.id == OWNER_ID)
@commands.cooldown(1, 10, commands.BucketType.guild)
async def sortear_cargos(ctx: commands.Context):
    guild = ctx.guild
    channel = get_sortear_channel(guild) or ctx.channel
    await ctx.send("Sorteando cargos, aguarde...")
    await executar_sorteio(guild, channel)


@bot.command(name="rank")
async def cmd_rank(ctx: commands.Context):
    guild = ctx.guild
    managed_roles = get_managed_roles(guild)
    if not managed_roles:
        await ctx.send("Nenhum cargo gerenciado encontrado.")
        return
    lines = []
    for role in managed_roles:
        if role.members:
            lines.append(f"**{role.name}:** {role.members[0].display_name}")
        else:
            lines.append(f"**{role.name}:** *(vazio)*")
    embed = discord.Embed(
        title="Hierarquia Atual",
        description="\n".join(lines),
        color=discord.Color.blurple()
    )
    embed.set_footer(text=hora_agora())
    await ctx.send(embed=embed)


@bot.command(name="top")
async def cmd_top(ctx: commands.Context):
    guild = ctx.guild
    msg = await ctx.send("Carregando ranking, aguarde...")
    if not os.path.exists(STATS_FILE):
        await msg.edit(content="Escaneando histórico do servidor pela primeira vez, aguarde...")
        await scan_audit_log(guild)
    stats = load_stats()
    if not stats:
        await msg.edit(content="Nenhum banimento ou expulsão registrado ainda.")
        return
    ranking = sorted(stats.items(), key=lambda x: x[1]["count"], reverse=True)
    ranking = [(uid, data) for uid, data in ranking if data.get("count", 0) > 0]
    if not ranking:
        await msg.edit(content="Nenhum banimento registrado ainda.")
        return
    embed = discord.Embed(title="🏆 Ranking de Fuzilamentos", description="Quem mais eliminou membros do servidor", color=discord.Color.red())
    medals = ["🥇", "🥈", "🥉"]
    for i, (user_id, data) in enumerate(ranking[:10]):
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        try:
            member = guild.get_member(int(user_id)) or await guild.fetch_member(int(user_id))
            name = member.display_name
        except Exception:
            name = data["name"]
        embed.add_field(name=f"{medal} {name}", value=f"**{data['count']}** eliminações", inline=False)
    if ranking:
        try:
            top_member = guild.get_member(int(ranking[0][0])) or await guild.fetch_member(int(ranking[0][0]))
            embed.set_thumbnail(url=top_member.display_avatar.url)
        except Exception:
            pass
    embed.set_footer(text=f"Atualizado em {hora_agora()}")
    await msg.edit(content=None, embed=embed)


@bot.command(name="fuzilados")
async def cmd_fuzilados(ctx: commands.Context):
    guild = ctx.guild
    msg = await ctx.send("Carregando ranking, aguarde...")
    if not os.path.exists(STATS_FILE):
        await msg.edit(content="Escaneando histórico do servidor pela primeira vez, aguarde...")
        await scan_audit_log(guild)
    stats = load_stats()
    if not stats:
        await msg.edit(content="Nenhum banimento ou expulsão registrado ainda.")
        return
    ranking = sorted([(uid, data) for uid, data in stats.items() if data.get("received", 0) > 0], key=lambda x: x[1]["received"], reverse=True)
    if not ranking:
        await msg.edit(content="Nenhuma vítima registrada ainda.")
        return
    embed = discord.Embed(title="💀 Ranking dos Fuzilados", description="Quem mais tomou ban/expulsão no servidor", color=discord.Color.dark_red())
    medals = ["🥇", "🥈", "🥉"]
    for i, (user_id, data) in enumerate(ranking[:10]):
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        try:
            member = guild.get_member(int(user_id)) or await guild.fetch_member(int(user_id))
            name = member.display_name
        except Exception:
            name = data["name"]
        embed.add_field(name=f"{medal} {name}", value=f"**{data['received']}** fuzilamento(s)", inline=False)
    if ranking:
        try:
            top_member = guild.get_member(int(ranking[0][0])) or await guild.fetch_member(int(ranking[0][0]))
            embed.set_thumbnail(url=top_member.display_avatar.url)
        except Exception:
            pass
    embed.set_footer(text=f"Atualizado em {hora_agora()}")
    await msg.edit(content=None, embed=embed)


@bot.command(name="67")
async def cmd_67(ctx: commands.Context):
    await tocar_audio(ctx.guild, "audio_67.mp3", maior_call=True)


@bot.command(name="tiki")
async def cmd_tiki(ctx: commands.Context):
    await tocar_audio(ctx.guild, "audio_tiki.mp3", maior_call=True)


@bot.command(name="rescan")
@commands.check(lambda ctx: ctx.author.id == OWNER_ID)
async def cmd_rescan(ctx: commands.Context):
    msg = await ctx.send("Rescaneando todo o histórico disponível, aguarde...")
    await scan_audit_log(ctx.guild)
    stats = load_stats()
    total = sum(v.get("count", 0) for v in stats.values())
    vitimas = sum(v.get("received", 0) for v in stats.values())
    await msg.edit(content=f"Rescan concluído! **{total}** ações encontradas, **{vitimas}** vítimas registradas.")


# ─── Inicialização ────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"[Bot] Conectado como {bot.user} (ID: {bot.user.id})")
    print(f"[Bot] Prefixo dos cargos: '{ROLE_PREFIX} N'")
    bot.loop.create_task(loop_sorteio_automatico())


bot.run(TOKEN)
