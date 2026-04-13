import discord
from discord.ext import commands
import re
import os
import random
import asyncio
import json
from datetime import datetime
import zoneinfo
from typing import Optional, List

# ─── Configuração ────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN")
ROLE_PREFIX = "Membro"
ROLE_COLOR = discord.Color.blurple()
INVITE_LINK = "https://discord.gg/m3BtpBhcy6"
OWNER_ID = 308987924559691788
LOG_CHANNEL = "banidos"
SORTEAR_CHANNEL = "geral"
SORTEAR_INTERVAL_DAYS = 2
AUDIO_FILE = "audio_banimento.mp3"  # Áudio tocado ao banir/expulsar
ALERT_MEMBER_ID = 501493721595117571  # Membro que dispara o alerta ao transmitir
STATS_FILE = "kick_ban_stats.json"  # Arquivo de estatísticas de banimentos/expulsões

# Controle do sorteio automático (em memória)
ultimo_sorteio: Optional[datetime] = None
sorteio_task_iniciado = False

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


# ─── Função: tocar áudio ao banir/expulsar ───────────────────────────────────

async def tocar_audio_banimento(guild: discord.Guild):
    """Entra na call com membros, toca o áudio e sai."""
    # Procura o primeiro canal de voz com ao menos 1 membro
    voice_channel = None
    for vc in guild.voice_channels:
        if len(vc.members) > 0:
            voice_channel = vc
            break

    if voice_channel is None:
        print("[Bot] Nenhuma call ativa encontrada, áudio não tocado.")
        return

    voice_client = None
    try:
        voice_client = await voice_channel.connect()
        print(f"[Bot] Entrou na call: {voice_channel.name}")

        # Converte MP3 para PCM usando pydub e toca como stream de bytes
        from pydub import AudioSegment
        import io
        print("[Bot] Convertendo áudio para PCM...")
        audio = AudioSegment.from_mp3(AUDIO_FILE)
        audio = audio.set_frame_rate(48000).set_channels(2).set_sample_width(2)
        pcm_data = audio.raw_data

        audio_source = discord.PCMAudio(io.BytesIO(pcm_data))
        voice_client.play(audio_source)
        print("[Bot] Tocando áudio via PCM...")

        # Aguarda o áudio terminar
        while voice_client.is_playing():
            await asyncio.sleep(1)

        await voice_client.disconnect()
        print("[Bot] Saiu da call após tocar o áudio.")
    except Exception as e:
        print(f"[Bot] Erro ao tocar áudio: {e}")
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()



# ─── Funções de estatísticas de ban/kick ─────────────────────────────────────

def load_stats() -> dict:
    """Carrega estatísticas do arquivo JSON."""
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_stats(stats: dict):
    """Salva estatísticas no arquivo JSON."""
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)


def increment_stat(executor_id: int, executor_name: str, victim_id: int = None, victim_name: str = None):
    """Incrementa o contador de um executor e registra a vítima."""
    stats = load_stats()

    # Contagem do executor (quem baniu/expulsou)
    key = str(executor_id)
    if key not in stats:
        stats[key] = {"name": executor_name, "count": 0, "received": 0}
    stats[key]["count"] += 1
    stats[key]["name"] = executor_name

    # Contagem da vítima (quem foi banido/expulso)
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
    """Varre todo o audit log disponível e popula as estatísticas."""
    # Carrega stats existentes para não perder dados já registrados
    stats = load_stats()
    # Garante campos necessários em entradas antigas
    for v in stats.values():
        if "count" not in v:
            v["count"] = 0
        if "received" not in v:
            v["received"] = 0

    actions = [discord.AuditLogAction.ban, discord.AuditLogAction.kick]
    for action in actions:
        try:
            # Busca em lotes de 100 (máximo permitido pela API)
            last_id = None
            while True:
                entries = []
                kwargs = {"limit": 100, "action": action}
                if last_id:
                    kwargs["before"] = discord.Object(id=last_id)
                async for entry in guild.audit_logs(**kwargs):
                    entries.append(entry)
                    # Executor
                    key = str(entry.user.id)
                    if key not in stats:
                        stats[key] = {"name": entry.user.display_name, "count": 0, "received": 0}
                    stats[key]["count"] += 1
                    stats[key]["name"] = entry.user.display_name
                    # Vítima
                    vkey = str(entry.target.id)
                    if vkey not in stats:
                        stats[vkey] = {"name": str(entry.target), "count": 0, "received": 0}
                    stats[vkey]["received"] += 1
                if len(entries) < 100:
                    break  # Não há mais entradas
                last_id = entries[-1].id
        except discord.Forbidden:
            pass

    save_stats(stats)
    total = sum(v.get("count", 0) for v in stats.values())
    print(f"[Bot] Audit log escaneado: {total} ações registradas.")


# ─── Lógica central do sorteio ───────────────────────────────────────────────

async def executar_sorteio(guild: discord.Guild, channel: discord.TextChannel):
    """Executa o sorteio e envia o resultado no canal informado."""
    global ultimo_sorteio

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
        await channel.send("❌ Nenhum membro com cargos gerenciados encontrado.")
        return

    # Remove todos os cargos gerenciados
    for member in members_with_roles:
        roles_to_remove = [r for r in member.roles if r.id in managed_role_ids]
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="Sorteio: limpando cargos antigos")

    # Embaralha
    random.shuffle(members_with_roles)

    # Garante cargos suficientes
    managed_roles = get_managed_roles(guild)
    while len(managed_roles) < len(members_with_roles):
        new_role = await create_next_role(guild, managed_roles)
        managed_roles.append(new_role)

    # Atribui e monta mensagem
    lines = ["🎲 **Nova hierarquia de cargos atualizada.** @everyone\n"]
    for i, member in enumerate(members_with_roles):
        role = managed_roles[i]
        await member.add_roles(role, reason="Sorteio de cargos")
        lines.append(f"**{role.name}:** {member.display_name}")
        print(f"[Bot] Sorteio: {member.display_name} → {role.name}")

    await channel.send("\n".join(lines))

    # Registra o horário do último sorteio
    tz = zoneinfo.ZoneInfo("America/Sao_Paulo")
    ultimo_sorteio = datetime.now(tz)
    print(f"[Bot] Sorteio concluído para {len(members_with_roles)} membros. Próximo em {SORTEAR_INTERVAL_DAYS} dias.")


# ─── Loop automático de sorteio ──────────────────────────────────────────────

async def loop_sorteio_automatico():
    """Aguarda 2 dias após o início do bot e repete automaticamente."""
    global ultimo_sorteio
    await bot.wait_until_ready()

    # Inicia o timer a partir do momento que o bot sobe
    tz = zoneinfo.ZoneInfo("America/Sao_Paulo")
    if ultimo_sorteio is None:
        ultimo_sorteio = datetime.now(tz)
        print(f"[Bot] Timer do sorteio automático iniciado: {ultimo_sorteio.strftime('%d/%m/%Y %H:%M')}")

    while not bot.is_closed():
        await asyncio.sleep(60)  # Verifica a cada 1 minuto

        agora = datetime.now(tz)
        diff = (agora - ultimo_sorteio).total_seconds()
        intervalo = SORTEAR_INTERVAL_DAYS * 24 * 60 * 60  # 2 dias em segundos

        if diff >= intervalo:
            print("[Bot] Disparando sorteio automático...")
            for guild in bot.guilds:
                channel = get_sortear_channel(guild)
                if channel:
                    await channel.send("🔀 Sorteando cargos automaticamente, aguarde...")
                    await executar_sorteio(guild, channel)


# ─── Evento: impede atribuição manual de cargos gerenciados ──────────────────

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    guild = after.guild
    managed_roles = get_managed_roles(guild)
    managed_role_ids = {r.id: r for r in managed_roles}

    # Cargos que foram adicionados nesta atualização
    roles_added = set(after.roles) - set(before.roles)

    # Cargos que foram removidos nesta atualização
    roles_removed = set(before.roles) - set(after.roles)

    for role in roles_added:
        if role.id not in managed_role_ids:
            continue  # Não é um cargo gerenciado, ignora

        # Verifica no audit log se foi o bot que atribuiu
        try:
            async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.member_role_update):
                if entry.target.id == after.id:
                    if entry.user.id == bot.user.id:
                        return  # Foi o próprio bot, permitido
                    # Foi outra pessoa — remove o cargo
                    await after.remove_roles(role, reason="Atribuição manual bloqueada pelo bot")
                    print(f"[Bot] Cargo '{role.name}' removido de {after.display_name} (atribuição manual bloqueada)")
                    return
        except discord.Forbidden:
            pass

    for role in roles_removed:
        if role.id not in managed_role_ids:
            continue  # Não é um cargo gerenciado, ignora

        # Verifica no audit log se foi o bot que removeu
        try:
            async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.member_role_update):
                if entry.target.id == after.id:
                    if entry.user.id == bot.user.id:
                        return  # Foi o próprio bot, permitido
                    # Foi outra pessoa — restaura o cargo
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

    try:
        await guild.fetch_ban(member)
        is_ban = True
    except discord.NotFound:
        is_ban = False

    managed_roles = get_managed_roles(guild)
    managed_role_ids = {parse_role_number(r): r for r in managed_roles}
    numero_saiu = None
    for num, role in managed_role_ids.items():
        if role in member.roles:
            numero_saiu = num
            break
    if numero_saiu is not None:
        print(f"[Bot] {member.display_name} saiu do {ROLE_PREFIX} {numero_saiu}, reajustando...")
        await reajustar_hierarquia(guild, numero_saiu)

    channel = get_log_channel(guild)

    if is_ban:
        return

    executor_name = None
    is_kick = False
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
            if entry.target.id == member.id:
                is_kick = True
                executor_name = entry.user.display_name
                break
    except discord.Forbidden:
        pass

    if channel:
        if is_kick:
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
            await channel.send(embed=embed)
            await send_invite(member, "foi expulso")
            await tocar_audio_banimento(guild)
            if executor_name:
                increment_stat(entry.user.id, executor_name, member.id, member.display_name)
        else:
            embed = discord.Embed(
                description=f"**{member.display_name}** saiu do servidor.",
                color=discord.Color.light_grey()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"ID: {member.id} • {hora_agora()}")
            await channel.send(embed=embed)
            await send_invite(member, "saiu")


# ─── Evento: membro foi banido ────────────────────────────────────────────────

@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    await send_invite(user, "foi banido")
    await tocar_audio_banimento(guild)

    # Registra o banimento nas estatísticas
    try:
        async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.ban):
            if entry.target.id == user.id:
                increment_stat(entry.user.id, entry.user.display_name, user.id, user.display_name)
                break
    except discord.Forbidden:
        pass

    executor_name = None
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
            if entry.target.id == user.id:
                executor_name = entry.user.display_name
                break
    except discord.Forbidden:
        pass

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
@commands.check(lambda ctx: ctx.author.id == OWNER_ID)
@commands.cooldown(1, 10, commands.BucketType.guild)
async def sortear_cargos(ctx: commands.Context):
    guild = ctx.guild
    channel = get_sortear_channel(guild) or ctx.channel
    await ctx.send("🔀 Sorteando cargos, aguarde...")
    await executar_sorteio(guild, channel)
    print("[Bot] Sorteio manual executado. Loop automático iniciado.")


# ─── Comando: !67 — toca áudio na call com mais membros ─────────────────────

@bot.command(name="67")
async def cmd_67(ctx: commands.Context):
    guild = ctx.guild

    # Encontra o canal de voz com MAIS membros (mínimo 1)
    voice_channel = None
    max_members = 0
    for vc in guild.voice_channels:
        if len(vc.members) > max_members:
            max_members = len(vc.members)
            voice_channel = vc

    if voice_channel is None:
        await ctx.send("Nenhuma call ativa encontrada.")
        return

    voice_client = None
    try:
        voice_client = await voice_channel.connect()
        print(f"[Bot] !67 — Entrou na call: {voice_channel.name}")

        from pydub import AudioSegment
        import io
        audio = AudioSegment.from_mp3("audio_67.mp3")
        audio = audio.set_frame_rate(48000).set_channels(2).set_sample_width(2)
        pcm_data = audio.raw_data

        audio_source = discord.PCMAudio(io.BytesIO(pcm_data))
        voice_client.play(audio_source)

        while voice_client.is_playing():
            await asyncio.sleep(1)

        await voice_client.disconnect()
        print("[Bot] !67 — Saiu da call.")
    except Exception as e:
        print(f"[Bot] !67 — Erro: {e}")
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()


# ─── Comando: !tiki — toca áudio na call com mais membros ───────────────────

@bot.command(name="tiki")
async def cmd_tiki(ctx: commands.Context):
    guild = ctx.guild

    voice_channel = None
    max_members = 0
    for vc in guild.voice_channels:
        if len(vc.members) > max_members:
            max_members = len(vc.members)
            voice_channel = vc

    if voice_channel is None:
        await ctx.send("Nenhuma call ativa encontrada.")
        return

    voice_client = None
    try:
        voice_client = await voice_channel.connect()
        print(f"[Bot] !tiki — Entrou na call: {voice_channel.name}")

        from pydub import AudioSegment
        import io
        audio = AudioSegment.from_mp3("audio_tiki.mp3")
        audio = audio.set_frame_rate(48000).set_channels(2).set_sample_width(2)
        pcm_data = audio.raw_data

        audio_source = discord.PCMAudio(io.BytesIO(pcm_data))
        voice_client.play(audio_source)

        while voice_client.is_playing():
            await asyncio.sleep(1)

        await voice_client.disconnect()
        print("[Bot] !tiki — Saiu da call.")
    except Exception as e:
        print(f"[Bot] !tiki — Erro: {e}")
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()


# ─── Evento: responde com vídeo ao mencionar "monster" ───────────────────────

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Verifica se a mensagem contém "monster" ou "monstre" (ignora maiúsculas)
    palavras = re.findall(r'\b(monsters?|monstre)\b', message.content, re.IGNORECASE)
    if palavras:
        await message.channel.send(file=discord.File("monster.mp4"))

    # Verifica se a mensagem contém variações de "obrigado/brigado pela/pera lata"
    if re.search(r'\b(obrigad[oa]|brigad[oa])\b.{0,20}\b(pela|pera)\b.{0,10}\b(lata)\b', message.content, re.IGNORECASE):
        await message.channel.send("**De nada Chefe!**")

    # Necessário para os comandos continuarem funcionando
    await bot.process_commands(message)


# ─── Comando: !top — ranking de banimentos/expulsões ─────────────────────────

@bot.command(name="top")
async def cmd_top(ctx: commands.Context):
    guild = ctx.guild
    msg = await ctx.send("🔍 Carregando ranking, aguarde...")

    # Na primeira vez ou se o arquivo não existir, escaneia o audit log
    if not os.path.exists(STATS_FILE):
        await msg.edit(content="🔍 Escaneando histórico do servidor pela primeira vez, aguarde...")
        await scan_audit_log(guild)

    stats = load_stats()
    if not stats:
        await msg.edit(content="Nenhum banimento ou expulsão registrado ainda.")
        return

    # Ordena do maior para o menor
    ranking = sorted(stats.items(), key=lambda x: x[1]["count"], reverse=True)

    embed = discord.Embed(
        title="🏆 Ranking de Fuzilamentos",
        description="Quem mais eliminou membros do servidor",
        color=discord.Color.red()
    )

    medals = ["🥇", "🥈", "🥉"]
    for i, (user_id, data) in enumerate(ranking[:10]):
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        try:
            member = guild.get_member(int(user_id)) or await guild.fetch_member(int(user_id))
            avatar_url = member.display_avatar.url
            name = member.display_name
        except Exception:
            avatar_url = None
            name = data["name"]

        embed.add_field(
            name=f"{medal} {name}",
            value=f"**{data['count']}** eliminações",
            inline=False
        )

    # Foto do líder no topo
    if ranking:
        top_id = ranking[0][0]
        try:
            top_member = guild.get_member(int(top_id)) or await guild.fetch_member(int(top_id))
            embed.set_thumbnail(url=top_member.display_avatar.url)
        except Exception:
            pass

    embed.set_footer(text=f"Atualizado em {hora_agora()}")
    await msg.edit(content=None, embed=embed)



# ─── Comando: !fuzilados — ranking de quem mais foi banido/expulso ────────────

@bot.command(name="fuzilados")
async def cmd_fuzilados(ctx: commands.Context):
    guild = ctx.guild
    msg = await ctx.send("🔍 Carregando ranking, aguarde...")

    if not os.path.exists(STATS_FILE):
        await msg.edit(content="🔍 Escaneando histórico do servidor pela primeira vez, aguarde...")
        await scan_audit_log(guild)

    stats = load_stats()
    if not stats:
        await msg.edit(content="Nenhum banimento ou expulsão registrado ainda.")
        return

    # Filtra só quem tem received > 0, ordena do maior para o menor
    ranking = sorted(
        [(uid, data) for uid, data in stats.items() if data.get("received", 0) > 0],
        key=lambda x: x[1]["received"],
        reverse=True
    )

    if not ranking:
        await msg.edit(content="Nenhuma vítima registrada ainda.")
        return

    embed = discord.Embed(
        title="💀 Ranking dos Fuzilados",
        description="Quem mais tomou ban/expulsão no servidor",
        color=discord.Color.dark_red()
    )

    medals = ["🥇", "🥈", "🥉"]
    for i, (user_id, data) in enumerate(ranking[:10]):
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        try:
            member = guild.get_member(int(user_id)) or await guild.fetch_member(int(user_id))
            name = member.display_name
            avatar_url = member.display_avatar.url
        except Exception:
            name = data["name"]
            avatar_url = None

        embed.add_field(
            name=f"{medal} {name}",
            value=f"**{data['received']}** fuzilamento(s)",
            inline=False
        )

    # Foto do líder no topo
    if ranking:
        top_id = ranking[0][0]
        try:
            top_member = guild.get_member(int(top_id)) or await guild.fetch_member(int(top_id))
            embed.set_thumbnail(url=top_member.display_avatar.url)
        except Exception:
            pass

    embed.set_footer(text=f"Atualizado em {hora_agora()}")
    await msg.edit(content=None, embed=embed)

# ─── Comando: !tempo — tempo restante para o próximo sorteio ────────────────

@bot.command(name="tempo")
async def cmd_tempo(ctx: commands.Context):
    if ultimo_sorteio is None:
        await ctx.send("⏳ O timer ainda não foi iniciado.")
        return

    tz = zoneinfo.ZoneInfo("America/Sao_Paulo")
    agora = datetime.now(tz)
    intervalo = SORTEAR_INTERVAL_DAYS * 24 * 60 * 60
    diff = (agora - ultimo_sorteio).total_seconds()
    restante = intervalo - diff

    if restante <= 0:
        await ctx.send("🎲 O sorteio automático está prestes a acontecer!")
        return

    dias = int(restante // 86400)
    horas = int((restante % 86400) // 3600)
    minutos = int((restante % 3600) // 60)

    proximo = ultimo_sorteio.timestamp() + intervalo
    proximo_dt = datetime.fromtimestamp(proximo, tz=tz)
    proximo_str = proximo_dt.strftime("%d/%m/%Y às %H:%M")

    await ctx.send(
        f"⏳ **Proximo sorteio automatico em:**\n"
        f"**{dias}d {horas}h {minutos}min**\n"
        f"Previsto para: **{proximo_str}**"
    )


# ─── Comando: !meiotempo — reduz o timer pela metade ─────────────────────────

@bot.command(name="meiotempo")
@commands.check(lambda ctx: ctx.author.id == OWNER_ID)
async def cmd_meiotempo(ctx: commands.Context):
    global ultimo_sorteio
    if ultimo_sorteio is None:
        await ctx.send("⏳ O timer ainda não foi iniciado.")
        return

    tz = zoneinfo.ZoneInfo("America/Sao_Paulo")
    agora = datetime.now(tz)
    intervalo = SORTEAR_INTERVAL_DAYS * 24 * 60 * 60
    diff = (agora - ultimo_sorteio).total_seconds()
    restante = intervalo - diff

    # Avança o timer pela metade do tempo restante
    from datetime import timedelta
    ultimo_sorteio = agora - timedelta(seconds=(intervalo - restante / 2))

    novo_restante = restante / 2
    dias = int(novo_restante // 86400)
    horas = int((novo_restante % 86400) // 3600)
    minutos = int((novo_restante % 3600) // 60)

    await ctx.send(
        f"Timer reduzido pela metade!\n"
        f"Proximo sorteio em: **{dias}d {horas}h {minutos}min**"
    )
    print(f"[Bot] Timer reduzido pela metade por {ctx.author.display_name}.")


# ─── Comando: !rescan — força rescan do audit log ────────────────────────────

@bot.command(name="rescan")
@commands.check(lambda ctx: ctx.author.id == OWNER_ID)
async def cmd_rescan(ctx: commands.Context):
    msg = await ctx.send("🔍 Rescaneando todo o histórico disponível, aguarde...")
    await scan_audit_log(ctx.guild)
    stats = load_stats()
    total = sum(v.get("count", 0) for v in stats.values())
    vitimas = sum(v.get("received", 0) for v in stats.values())
    await msg.edit(content=f"✅ Rescan concluído! **{total}** ações de banimento/expulsão encontradas, **{vitimas}** vítimas registradas.")


# ─── Evento: alerta quando membro específico inicia transmissão ──────────────

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.id != ALERT_MEMBER_ID:
        return

    # Verifica se começou a transmitir (stream) agora
    estava_transmitindo = before.self_stream
    esta_transmitindo = after.self_stream

    if not estava_transmitindo and esta_transmitindo:
        guild = member.guild
        voice_channel = after.channel
        if voice_channel is None:
            return

        print(f"[Bot] {member.display_name} iniciou transmissão em {voice_channel.name}, entrando...")

        voice_client = None
        try:
            voice_client = await voice_channel.connect()

            from pydub import AudioSegment
            import io
            audio = AudioSegment.from_mp3("audio_alerta.mp3")
            audio = audio.set_frame_rate(48000).set_channels(2).set_sample_width(2)
            pcm_data = audio.raw_data

            audio_source = discord.PCMAudio(io.BytesIO(pcm_data))
            voice_client.play(audio_source)

            while voice_client.is_playing():
                await asyncio.sleep(1)

            await voice_client.disconnect()
            print("[Bot] Alerta tocado, saiu da call.")
        except Exception as e:
            print(f"[Bot] Erro no alerta de transmissão: {e}")
            if voice_client and voice_client.is_connected():
                await voice_client.disconnect()


# ─── Inicialização ────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"[Bot] Conectado como {bot.user} (ID: {bot.user.id})")
    print(f"[Bot] Prefixo dos cargos: '{ROLE_PREFIX} N'")
    bot.loop.create_task(loop_sorteio_automatico())


bot.run(TOKEN)
