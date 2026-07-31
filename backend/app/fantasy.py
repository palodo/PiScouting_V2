"""Fantasy FEB — motor de ligas por conferencia con mercado de subastas (estilo Biwenger).

Cómo funciona el mercado:
  - Cada liga elige DÍA de la semana y HORA (hora peninsular) a la que abre el mercado.
  - Al abrir, salen `market_size` jugadores LIBRES elegidos al azar pero repartidos por
    tramos de precio (siempre hay alguna estrella, gente media y chollos) → entretenido.
  - Los mánagers PUJAN en secreto (se ve cuánta gente ha pujado, no el importe).
  - Pasadas `market_duration_h` horas el mercado cierra: gana la puja más alta (a igualdad,
    la primera). El resto no paga nada. Luego se programa la siguiente apertura.
  - Todo se resuelve de forma perezosa (`sync_market`) en cada petición: no hace falta
    ningún proceso en segundo plano.

La valoración de jugadores es dinámica (VAL + forma + /- ponderado por fiabilidad) y los
puntos de cada jornada son la VAL del jugador + bonus si su equipo ganó.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from .config import FANTASY_COMPETITIONS
from .models import (
    Team, Player, Match, PlayerMatchStat,
    FantasyLeague, FantasyMember, FantasyPick, FantasyListing, FantasyBid, FantasyEvent,
)

try:  # hora peninsular para el horario del mercado
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Madrid")
except Exception:  # pragma: no cover - si falta tzdata, se usa UTC
    TZ = timezone.utc

# --- parámetros del modelo de precio ---
PRICE_K = 1.1
PRICE_MIN = 3.0
PRICE_MAX = 25.0
RECENT_N = 4  # partidos para la "forma reciente"
WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _pct(m, a):
    return round(100.0 * m / a, 1) if a else 0.0


# ============================ datos de la conferencia ============================
def conference_games(session: Session, comp: str, grupo: Optional[str], season: str) -> dict:
    """player_id -> {name, feb_code, team_id, team, games:[{j,val,pm,won}]} ordenado por jornada."""
    q = (
        select(PlayerMatchStat, Match, Player, Team)
        .join(Match, Match.id == PlayerMatchStat.match_id)
        .join(Player, Player.id == PlayerMatchStat.player_id)
        .join(Team, Team.id == PlayerMatchStat.team_id)
        .where(Team.competition == comp, Team.season == season)
    )
    if grupo:
        q = q.where(Team.grupo == grupo)
    out: dict[int, dict] = {}
    for st, m, pl, tm in session.exec(q).all():
        if m.jornada_num is None:
            continue
        my = m.home_score if st.is_home else m.away_score
        opp = m.away_score if st.is_home else m.home_score
        won = my is not None and opp is not None and my > opp
        d = out.setdefault(pl.id, {
            "player_id": pl.id, "name": pl.name, "feb_code": pl.feb_code,
            "team_id": tm.id, "team": tm.name, "games": [],
        })
        d["games"].append({"j": m.jornada_num, "val": st.val, "pm": st.plus_minus, "won": won})
    for d in out.values():
        d["games"].sort(key=lambda g: g["j"])
    return out


def max_jornada(session: Session, comp: str, grupo: Optional[str], season: str) -> int:
    q = select(Match).where(Match.competition == comp, Match.season == season)
    if grupo:
        q = q.where(Match.grupo == grupo)
    js = [m.jornada_num for m in session.exec(q).all() if m.jornada_num is not None]
    return max(js) if js else 0


# ============================ precio ============================
def _price_from_games(games: list[dict], up_to_j: int, team_games: int) -> float:
    played = [g for g in games if g["j"] <= up_to_j]
    if not played:
        return PRICE_MIN
    n = len(played)
    val_cum = sum(g["val"] for g in played) / n
    pm_cum = sum(g["pm"] for g in played) / n
    recent = played[-RECENT_N:]
    val_recent = sum(g["val"] for g in recent) / len(recent)
    reliab = min(1.0, n / max(1.0, 0.5 * team_games))
    raw = 0.6 * val_cum + 0.4 * val_recent + 0.3 * pm_cum
    return round(_clamp(PRICE_K * raw * (0.5 + 0.5 * reliab), PRICE_MIN, PRICE_MAX), 1)


def all_priced(session: Session, league: FantasyLeague) -> list[dict]:
    """Todos los jugadores de la conferencia con precio actual y stats."""
    conf = conference_games(session, league.competition, league.grupo, league.season)
    team_games: dict[int, int] = {}
    for d in conf.values():
        tg = len([g for g in d["games"] if g["j"] <= league.current_jornada])
        team_games[d["team_id"]] = max(team_games.get(d["team_id"], 0), tg)
    rows = []
    for d in conf.values():
        played = [g for g in d["games"] if g["j"] <= league.current_jornada]
        if not played:
            continue
        n = len(played)
        rows.append({
            "player_id": d["player_id"], "name": d["name"], "feb_code": d["feb_code"],
            "team_id": d["team_id"], "team": d["team"], "games": n,
            "price": _price_from_games(d["games"], league.current_jornada, team_games.get(d["team_id"], 1)),
            "val_avg": round(sum(g["val"] for g in played) / n, 1),
            "pm_avg": round(sum(g["pm"] for g in played) / n, 1),
            "form": round(sum(g["val"] for g in played[-RECENT_N:]) / len(played[-RECENT_N:]), 1),
        })
    rows.sort(key=lambda r: r["price"], reverse=True)
    return rows


def price_map(session: Session, league: FantasyLeague) -> dict[int, float]:
    return {r["player_id"]: r["price"] for r in all_priced(session, league)}


def owned_player_ids(session: Session, league_id: int) -> set[int]:
    members = session.exec(select(FantasyMember).where(FantasyMember.league_id == league_id)).all()
    mids = [m.id for m in members]
    if not mids:
        return set()
    picks = session.exec(select(FantasyPick).where(FantasyPick.member_id.in_(mids))).all()
    return {p.player_id for p in picks}


# ============================ horario del mercado ============================
def _next_slot(after: datetime, weekday: int, hour: int) -> datetime:
    """Siguiente día/hora de la semana (hora peninsular) tras `after`, devuelto en UTC naive."""
    local = after.replace(tzinfo=timezone.utc).astimezone(TZ)
    cand = local.replace(hour=int(hour) % 24, minute=0, second=0, microsecond=0)
    cand += timedelta(days=(int(weekday) - cand.weekday()) % 7)
    if cand <= local:
        cand += timedelta(days=7)
    return cand.astimezone(timezone.utc).replace(tzinfo=None)


def _log(session: Session, league_id: int, kind: str, text: str) -> None:
    session.add(FantasyEvent(league_id=league_id, kind=kind, text=text))


def _open_round(session: Session, league: FantasyLeague, now: datetime) -> None:
    """Saca una tanda aleatoria de jugadores libres, repartida por tramos de precio."""
    owned = owned_player_ids(session, league.id)
    pool = [r for r in all_priced(session, league) if r["player_id"] not in owned]
    if not pool:
        return
    rng = random.Random(f"{league.id}:{league.market_round + 1}:{league.season}")
    pool.sort(key=lambda r: r["price"], reverse=True)
    n = min(league.market_size, len(pool))
    # tramos: 20% estrellas, 50% medios, 30% chollos → mercado variado y entretenido
    cut1, cut2 = max(1, len(pool) // 5), max(2, len(pool) // 2)
    tiers = [pool[:cut1], pool[cut1:cut2], pool[cut2:]]
    want = [max(1, round(n * 0.2)), max(1, round(n * 0.5)), max(1, round(n * 0.3))]
    chosen: list[dict] = []
    for tier, k in zip(tiers, want):
        if tier:
            chosen += rng.sample(tier, min(k, len(tier)))
    rest = [r for r in pool if r not in chosen]
    if len(chosen) < n and rest:
        chosen += rng.sample(rest, min(n - len(chosen), len(rest)))
    rng.shuffle(chosen)

    league.market_round += 1
    league.market_open = True
    league.market_opens_at = now
    league.market_closes_at = now + timedelta(hours=league.market_duration_h)
    for r in chosen[:n]:
        session.add(FantasyListing(league_id=league.id, round_no=league.market_round,
                                   player_id=r["player_id"], price=r["price"]))
    _log(session, league.id, "market",
         f"🟢 Mercado abierto · {len(chosen[:n])} jugadores a subasta (jornada {league.market_round})")
    session.add(league)


def _resolve_round(session: Session, league: FantasyLeague) -> None:
    """Cierra la tanda: cada jugador va a la puja más alta (a igualdad, la primera)."""
    listings = session.exec(select(FantasyListing).where(
        FantasyListing.league_id == league.id,
        FantasyListing.round_no == league.market_round,
        FantasyListing.resolved == False)).all()  # noqa: E712
    sold = 0
    for lst in listings:
        bids = session.exec(select(FantasyBid).where(
            FantasyBid.listing_id == lst.id, FantasyBid.status == "active")).all()
        bids.sort(key=lambda b: (-b.amount, b.created_at))
        winner = None
        for b in bids:
            m = session.get(FantasyMember, b.member_id)
            picks = picks_of(session, m.id)
            if not m or b.amount > m.budget_remaining + 1e-6 or len(picks) >= league.squad_size:
                b.status = "lost"
                session.add(b)
                continue
            winner = (b, m)
            break
        for b in bids:
            if winner and b.id == winner[0].id:
                continue
            if b.status == "active":
                b.status = "lost"
                session.add(b)
        if winner:
            b, m = winner
            b.status = "won"
            m.budget_remaining = round(m.budget_remaining - b.amount, 1)
            starters = sum(1 for p in picks_of(session, m.id) if p.starter)
            _new_pick(session, league, m, lst.player_id, b.amount, lst.price,
                      starters < league.lineup_size)
            lst.winner_member_id = m.id
            lst.sold_price = b.amount
            sold += 1
            pl = session.get(Player, lst.player_id)
            _log(session, league.id, "signing",
                 f"✍️ {m.manager_name} ficha a {pl.name if pl else '?'} por {b.amount} M€")
            session.add_all([b, m])
        lst.resolved = True
        session.add(lst)
    league.market_open = False
    _log(session, league.id, "market", f"🔴 Mercado cerrado · {sold} fichajes")
    session.add(league)


def sync_market(session: Session, league: FantasyLeague) -> FantasyLeague:
    """Abre/cierra el mercado según el reloj. Idempotente y perezoso."""
    now = utcnow()
    changed = False
    for _ in range(10):  # guarda contra bucles
        if league.market_open and league.market_closes_at and now >= league.market_closes_at:
            _resolve_round(session, league)
            league.market_opens_at = _next_slot(now, league.market_weekday, league.market_hour)
            league.market_closes_at = None
            changed = True
            continue
        if not league.market_open and league.market_opens_at and now >= league.market_opens_at:
            _open_round(session, league, now)
            changed = True
            continue
        break
    if changed:
        session.commit()
        session.refresh(league)
    return league


# ============================ puntuación por jornada ============================
def jornada_points(session: Session, league: FantasyLeague, jornada: int) -> dict[int, float]:
    conf = conference_games(session, league.competition, league.grupo, league.season)
    out: dict[int, float] = {}
    for pid, d in conf.items():
        games = [g for g in d["games"] if g["j"] == jornada]
        if games:
            out[pid] = round(sum(g["val"] + (league.win_bonus if g["won"] else 0.0) for g in games), 1)
    return out


# ============================ ligas ============================
def _code(session: Session) -> str:
    while True:
        c = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not session.exec(select(FantasyLeague).where(FantasyLeague.join_code == c)).first():
            return c


def create_league(session: Session, owner_id: int, name: str, competition: str,
                  grupo: Optional[str], season: str, manager_name: str,
                  budget: float = 100.0, squad_size: int = 10, lineup_size: int = 5,
                  win_bonus: float = 4.0, start_jornada: Optional[int] = None,
                  market_weekday: int = 4, market_hour: int = 20,
                  market_duration_h: int = 24, market_size: int = 10,
                  initial_squad: int = 5, clause_factor: float = 2.0,
                  clause_lock_h: int = 24, open_now: bool = True) -> FantasyLeague:
    if competition not in FANTASY_COMPETITIONS:
        raise ValueError("Esa competición no está disponible para el fantasy.")
    mj = max_jornada(session, competition, grupo, season)
    if mj == 0:
        raise ValueError("Esa conferencia no tiene datos de partidos todavía")
    start = start_jornada if start_jornada is not None else max(3, round(mj * 0.35))
    start = int(_clamp(start, 1, mj - 1))
    now = utcnow()
    league = FantasyLeague(
        name=name, join_code=_code(session), owner_user_id=owner_id, season=season,
        competition=competition, grupo=grupo, budget=budget, squad_size=squad_size,
        lineup_size=lineup_size, initial_squad=initial_squad, win_bonus=win_bonus,
        start_jornada=start, current_jornada=start, max_jornada=mj,
        market_weekday=int(_clamp(market_weekday, 0, 6)), market_hour=int(_clamp(market_hour, 0, 23)),
        market_duration_h=int(_clamp(market_duration_h, 1, 168)),
        market_size=int(_clamp(market_size, 4, 30)),
        clause_factor=float(_clamp(clause_factor, 1.2, 5.0)),
        clause_lock_h=int(_clamp(clause_lock_h, 0, 168)),
        # el primer mercado abre ya (para poder jugar desde el minuto uno); los siguientes
        # siguen el horario elegido
        market_opens_at=now if open_now else _next_slot(now, market_weekday, market_hour),
    )
    session.add(league)
    session.commit()
    session.refresh(league)
    _log(session, league.id, "info", f"🏆 Liga creada · mercado los {WEEKDAYS[league.market_weekday]} "
                                     f"a las {league.market_hour:02d}:00 ({league.market_duration_h}h)")
    session.commit()
    join_league(session, league, owner_id, manager_name)
    sync_market(session, league)
    return league


def _assign_initial_squad(session: Session, league: FantasyLeague, member: FantasyMember) -> None:
    """Plantilla inicial aleatoria para poder jugar desde el primer momento."""
    if league.initial_squad <= 0:
        return
    owned = owned_player_ids(session, league.id)
    pool = [r for r in all_priced(session, league) if r["player_id"] not in owned]
    if not pool:
        return
    rng = random.Random(f"{league.id}:init:{member.id}")
    budget_cap = league.budget * 0.45
    rng.shuffle(pool)
    spent = 0.0
    for r in pool:
        if sum(1 for _ in picks_of(session, member.id)) >= league.initial_squad:
            break
        if spent + r["price"] > budget_cap:
            continue
        starters = sum(1 for p in picks_of(session, member.id) if p.starter)
        _new_pick(session, league, member, r["player_id"], r["price"], r["price"],
                  starters < league.lineup_size)
        spent += r["price"]
        session.commit()
    member.budget_remaining = round(member.budget_remaining - spent, 1)
    session.add(member)
    session.commit()


def join_league(session: Session, league: FantasyLeague, user_id: int, manager_name: str) -> FantasyMember:
    existing = session.exec(select(FantasyMember).where(
        FantasyMember.league_id == league.id, FantasyMember.user_id == user_id)).first()
    if existing:
        return existing
    m = FantasyMember(league_id=league.id, user_id=user_id, manager_name=manager_name,
                      budget_remaining=league.budget)
    session.add(m)
    session.commit()
    session.refresh(m)
    _assign_initial_squad(session, league, m)
    _log(session, league.id, "join", f"👋 {manager_name} se une a la liga")
    session.commit()
    return m


def member_of(session: Session, league_id: int, user_id: int) -> Optional[FantasyMember]:
    return session.exec(select(FantasyMember).where(
        FantasyMember.league_id == league_id, FantasyMember.user_id == user_id)).first()


def picks_of(session: Session, member_id: int) -> list[FantasyPick]:
    return session.exec(select(FantasyPick).where(FantasyPick.member_id == member_id)).all()


# ============================ mercado / pujas ============================
def market(session: Session, league: FantasyLeague, member: Optional[FantasyMember]) -> dict:
    """Subastas abiertas de la tanda actual, con info de mis pujas."""
    sync_market(session, league)
    listings = session.exec(select(FantasyListing).where(
        FantasyListing.league_id == league.id,
        FantasyListing.round_no == league.market_round,
        FantasyListing.resolved == False)).all()  # noqa: E712
    info = {r["player_id"]: r for r in all_priced(session, league)}
    my_bids = {}
    if member:
        for b in session.exec(select(FantasyBid).where(
                FantasyBid.member_id == member.id, FantasyBid.status == "active")).all():
            my_bids[b.listing_id] = b
    rows = []
    for lst in listings:
        d = info.get(lst.player_id, {})
        n_bids = len(session.exec(select(FantasyBid).where(
            FantasyBid.listing_id == lst.id, FantasyBid.status == "active")).all())
        mine = my_bids.get(lst.id)
        rows.append({
            "listing_id": lst.id, "player_id": lst.player_id,
            "name": d.get("name", "?"), "feb_code": d.get("feb_code"), "team": d.get("team"),
            "price": lst.price, "val_avg": d.get("val_avg", 0), "pm_avg": d.get("pm_avg", 0),
            "form": d.get("form", 0), "bids": n_bids,
            "my_bid": mine.amount if mine else None,
        })
    rows.sort(key=lambda r: r["price"], reverse=True)
    return {
        "open": league.market_open,
        "round": league.market_round,
        "closes_at": league.market_closes_at.isoformat() + "Z" if league.market_closes_at else None,
        "opens_at": league.market_opens_at.isoformat() + "Z" if league.market_opens_at else None,
        "listings": rows,
        "my_budget": member.budget_remaining if member else None,
        "committed": committed_amount(session, member.id) if member else 0.0,
    }


def committed_amount(session: Session, member_id: int) -> float:
    bids = session.exec(select(FantasyBid).where(
        FantasyBid.member_id == member_id, FantasyBid.status == "active")).all()
    return round(sum(b.amount for b in bids), 1)


def place_bid(session: Session, league: FantasyLeague, member: FantasyMember,
              listing_id: int, amount: float) -> dict:
    sync_market(session, league)
    if not league.market_open:
        raise ValueError("El mercado está cerrado")
    lst = session.get(FantasyListing, listing_id)
    if not lst or lst.league_id != league.id or lst.resolved or lst.round_no != league.market_round:
        raise ValueError("Esa subasta ya no está disponible")
    if len(picks_of(session, member.id)) >= league.squad_size:
        raise ValueError(f"Plantilla llena ({league.squad_size} jugadores)")
    amount = round(float(amount), 1)
    if amount < lst.price:
        raise ValueError(f"La puja mínima es {lst.price} M€")
    prev = session.exec(select(FantasyBid).where(
        FantasyBid.listing_id == lst.id, FantasyBid.member_id == member.id,
        FantasyBid.status == "active")).first()
    other = committed_amount(session, member.id) - (prev.amount if prev else 0.0)
    if amount + other > member.budget_remaining + 1e-6:
        raise ValueError("No te llega el presupuesto con las pujas que ya tienes")
    if prev:
        prev.amount = amount
        session.add(prev)
    else:
        session.add(FantasyBid(league_id=league.id, listing_id=lst.id,
                               member_id=member.id, amount=amount))
    session.commit()
    return {"ok": True, "amount": amount}


def cancel_bid(session: Session, league: FantasyLeague, member: FantasyMember, listing_id: int) -> dict:
    bid = session.exec(select(FantasyBid).where(
        FantasyBid.listing_id == listing_id, FantasyBid.member_id == member.id,
        FantasyBid.status == "active")).first()
    if not bid:
        raise ValueError("No tienes una puja ahí")
    bid.status = "cancelled"
    session.add(bid)
    session.commit()
    return {"ok": True}


def close_market_now(session: Session, league: FantasyLeague) -> dict:
    """Cierra la tanda actual ya (para probar sin esperar al horario)."""
    sync_market(session, league)
    if not league.market_open:
        raise ValueError("El mercado ya está cerrado")
    _resolve_round(session, league)
    league.market_opens_at = _next_slot(utcnow(), league.market_weekday, league.market_hour)
    league.market_closes_at = None
    session.add(league)
    session.commit()
    session.refresh(league)
    return {"ok": True, "round": league.market_round}


def open_market_now(session: Session, league: FantasyLeague) -> dict:
    """Abre una tanda ya (para probar sin esperar al horario)."""
    sync_market(session, league)
    if league.market_open:
        raise ValueError("El mercado ya está abierto")
    _open_round(session, league, utcnow())
    session.commit()
    session.refresh(league)
    return {"ok": True, "round": league.market_round}


# ============================ cláusulas de rescisión ============================
def _clause_for(league: FantasyLeague, value: float) -> float:
    return round(max(value, PRICE_MIN) * league.clause_factor, 1)


def _new_pick(session: Session, league: FantasyLeague, member: FantasyMember,
              player_id: int, paid: float, value: float, starter: bool) -> FantasyPick:
    pick = FantasyPick(
        member_id=member.id, player_id=player_id, buy_price=paid,
        buy_jornada=league.current_jornada, starter=starter,
        clause=_clause_for(league, max(value, paid)),
        clause_locked_until=utcnow() + timedelta(hours=league.clause_lock_h),
    )
    session.add(pick)
    return pick


def pay_clause(session: Session, league: FantasyLeague, member: FantasyMember,
               player_id: int) -> dict:
    """Clausulazo: te llevas al jugador de otro mánager pagando su cláusula (el dinero
    va íntegro al dueño)."""
    pick = session.exec(select(FantasyPick).join(
        FantasyMember, FantasyMember.id == FantasyPick.member_id).where(
        FantasyMember.league_id == league.id, FantasyPick.player_id == player_id)).first()
    if not pick:
        raise ValueError("Ese jugador no lo tiene nadie: ficha por el mercado")
    if pick.member_id == member.id:
        raise ValueError("Ese jugador ya es tuyo")
    if pick.clause_locked_until and utcnow() < pick.clause_locked_until:
        mins = int((pick.clause_locked_until - utcnow()).total_seconds() // 60)
        raise ValueError(f"Jugador blindado {mins // 60}h {mins % 60}m más")
    if len(picks_of(session, member.id)) >= league.squad_size:
        raise ValueError(f"Plantilla llena ({league.squad_size} jugadores)")
    amount = round(pick.clause, 1)
    free = member.budget_remaining - committed_amount(session, member.id)
    if amount > free + 1e-6:
        raise ValueError(f"Necesitas {amount} M€ libres (tienes {round(free, 1)})")

    owner = session.get(FantasyMember, pick.member_id)
    value = price_map(session, league).get(player_id, amount)
    member.budget_remaining = round(member.budget_remaining - amount, 1)
    owner.budget_remaining = round(owner.budget_remaining + amount, 1)
    starters = sum(1 for p in picks_of(session, member.id) if p.starter)
    session.delete(pick)
    _new_pick(session, league, member, player_id, amount, value, starters < league.lineup_size)
    session.add_all([member, owner])
    pl = session.get(Player, player_id)
    _log(session, league.id, "clause",
         f"💥 CLAUSULAZO · {member.manager_name} se lleva a {pl.name if pl else '?'} "
         f"de {owner.manager_name} por {amount} M€")
    session.commit()
    return {"ok": True, "paid": amount, "budget_remaining": member.budget_remaining}


def raise_clause(session: Session, league: FantasyLeague, member: FantasyMember,
                 player_id: int, new_clause: float) -> dict:
    """Sube la cláusula de tu jugador. Cuesta un % de la subida."""
    pick = session.exec(select(FantasyPick).where(
        FantasyPick.member_id == member.id, FantasyPick.player_id == player_id)).first()
    if not pick:
        raise ValueError("No tienes a ese jugador")
    new_clause = round(float(new_clause), 1)
    if new_clause <= pick.clause:
        raise ValueError(f"La cláusula ya es de {pick.clause} M€")
    cost = round((new_clause - pick.clause) * league.clause_raise_cost, 1)
    free = member.budget_remaining - committed_amount(session, member.id)
    if cost > free + 1e-6:
        raise ValueError(f"Subirla cuesta {cost} M€ y solo tienes {round(free, 1)} libres")
    pick.clause = new_clause
    member.budget_remaining = round(member.budget_remaining - cost, 1)
    session.add_all([pick, member])
    session.commit()
    return {"ok": True, "clause": new_clause, "cost": cost,
            "budget_remaining": member.budget_remaining}


# ============================ ficha del jugador ============================
def player_detail(session: Session, league: FantasyLeague, player_id: int) -> dict:
    """Todas las estadísticas del jugador + su situación en la liga (dueño, cláusula)."""
    pl = session.get(Player, player_id)
    if not pl:
        raise ValueError("Jugador no encontrado")
    rows = session.exec(
        select(PlayerMatchStat, Match, Team)
        .join(Match, Match.id == PlayerMatchStat.match_id)
        .join(Team, Team.id == PlayerMatchStat.team_id)
        .where(PlayerMatchStat.player_id == player_id, Team.season == league.season)
    ).all()
    agg = {k: 0 for k in ("seconds", "pts", "val", "plus_minus", "treb", "oreb", "dreb", "ast",
                          "stl", "tov", "blk_for", "pf_committed", "t2m", "t2a", "t3m", "t3a",
                          "tlm", "tla")}
    games, team_name, wins = [], None, 0
    for st, m, tm in rows:
        team_name = tm.name
        for k in agg:
            agg[k] += getattr(st, k)
        my = m.home_score if st.is_home else m.away_score
        opp = m.away_score if st.is_home else m.home_score
        won = my is not None and opp is not None and my > opp
        wins += int(won)
        games.append({"j": m.jornada_num, "val": st.val, "pts": st.pts, "reb": st.treb,
                      "ast": st.ast, "pm": st.plus_minus, "min": round(st.seconds / 60, 1),
                      "won": won})
    n = len(rows) or 1
    fga, fgm = agg["t2a"] + agg["t3a"], agg["t2m"] + agg["t3m"]
    ts_den = 2 * (fga + 0.44 * agg["tla"])
    games.sort(key=lambda g: g["j"] or 0)
    info = next((r for r in all_priced(session, league) if r["player_id"] == player_id), {})

    pick = session.exec(select(FantasyPick).join(
        FantasyMember, FantasyMember.id == FantasyPick.member_id).where(
        FantasyMember.league_id == league.id, FantasyPick.player_id == player_id)).first()
    owner = session.get(FantasyMember, pick.member_id) if pick else None
    locked = bool(pick and pick.clause_locked_until and utcnow() < pick.clause_locked_until)
    lock_mins = int((pick.clause_locked_until - utcnow()).total_seconds() // 60) if locked else 0

    return {
        "player_id": player_id, "name": pl.name, "feb_code": pl.feb_code, "team": team_name,
        "price": info.get("price"), "form": info.get("form"), "games": len(rows),
        "wins": wins, "losses": len(rows) - wins,
        "avg": {
            "min": round(agg["seconds"] / n / 60, 1), "pts": round(agg["pts"] / n, 1),
            "reb": round(agg["treb"] / n, 1), "oreb": round(agg["oreb"] / n, 1),
            "dreb": round(agg["dreb"] / n, 1), "ast": round(agg["ast"] / n, 1),
            "stl": round(agg["stl"] / n, 1), "tov": round(agg["tov"] / n, 1),
            "blk": round(agg["blk_for"] / n, 1), "pf": round(agg["pf_committed"] / n, 1),
            "val": round(agg["val"] / n, 1), "pm": round(agg["plus_minus"] / n, 1),
        },
        "pct": {
            "fg": _pct(fgm, fga), "t2": _pct(agg["t2m"], agg["t2a"]),
            "t3": _pct(agg["t3m"], agg["t3a"]), "tl": _pct(agg["tlm"], agg["tla"]),
            "ts": round(agg["pts"] / ts_den * 100, 1) if ts_den else 0.0,
        },
        "totals": {"pts": agg["pts"], "val": agg["val"], "t3m": agg["t3m"]},
        "last": games[-8:],
        "owner": owner.manager_name if owner else None,
        "owner_member_id": owner.id if owner else None,
        "clause": pick.clause if pick else None,
        "clause_locked": locked, "clause_lock_mins": lock_mins,
    }


def member_squad(session: Session, league: FantasyLeague, member_id: int) -> list[dict]:
    """Plantilla de cualquier mánager (para ver rivales y sus cláusulas)."""
    m = session.get(FantasyMember, member_id)
    if not m or m.league_id != league.id:
        raise ValueError("Mánager no encontrado")
    prices = price_map(session, league)
    info = {r["player_id"]: r for r in all_priced(session, league)}
    now = utcnow()
    out = []
    for p in picks_of(session, member_id):
        d = info.get(p.player_id, {})
        locked = bool(p.clause_locked_until and now < p.clause_locked_until)
        out.append({
            "player_id": p.player_id, "name": d.get("name", "?"), "feb_code": d.get("feb_code"),
            "team": d.get("team"), "price": prices.get(p.player_id, p.buy_price),
            "val_avg": d.get("val_avg", 0), "starter": p.starter,
            "clause": p.clause, "clause_locked": locked,
            "clause_lock_mins": int((p.clause_locked_until - now).total_seconds() // 60) if locked else 0,
        })
    out.sort(key=lambda r: -r["price"])
    return {"manager": m.manager_name, "member_id": m.id, "squad": out,
            "budget": m.budget_remaining, "points": m.total_points}


def sell(session: Session, league: FantasyLeague, member: FantasyMember, player_id: int) -> dict:
    pick = session.exec(select(FantasyPick).where(
        FantasyPick.member_id == member.id, FantasyPick.player_id == player_id)).first()
    if not pick:
        raise ValueError("No tienes a ese jugador")
    price = price_map(session, league).get(player_id, pick.buy_price)
    member.budget_remaining = round(member.budget_remaining + price, 1)
    session.delete(pick)
    session.add(member)
    pl = session.get(Player, player_id)
    _log(session, league.id, "sale", f"💸 {member.manager_name} vende a {pl.name if pl else '?'} por {price} M€")
    session.commit()
    return {"ok": True, "price": price, "budget_remaining": member.budget_remaining}


def set_lineup(session: Session, league: FantasyLeague, member: FantasyMember,
               starter_ids: list[int]) -> dict:
    if len(starter_ids) > league.lineup_size:
        raise ValueError(f"Solo puedes alinear {league.lineup_size} titulares")
    picks = picks_of(session, member.id)
    if not set(starter_ids).issubset({p.player_id for p in picks}):
        raise ValueError("Algún titular no está en tu plantilla")
    for p in picks:
        p.starter = p.player_id in starter_ids
        session.add(p)
    session.commit()
    return {"ok": True, "starters": starter_ids}


# ============================ jornada / clasificación ============================
def advance(session: Session, league: FantasyLeague) -> dict:
    if league.current_jornada >= league.max_jornada:
        return {"ok": False, "done": True, "message": "La temporada ya está completa"}
    nxt = league.current_jornada + 1
    pts = jornada_points(session, league, nxt)
    members = session.exec(select(FantasyMember).where(FantasyMember.league_id == league.id)).all()
    breakdown = []
    for m in members:
        gained = round(sum(pts.get(p.player_id, 0.0) for p in picks_of(session, m.id) if p.starter), 1)
        m.total_points = round(m.total_points + gained, 1)
        session.add(m)
        breakdown.append({"member_id": m.id, "manager": m.manager_name, "gained": gained})
    league.current_jornada = nxt
    session.add(league)
    best = max(breakdown, key=lambda b: b["gained"], default=None)
    _log(session, league.id, "jornada",
         f"📅 Jornada {nxt} puntuada" + (f" · mejor: {best['manager']} ({best['gained']} pts)" if best else ""))
    session.commit()
    return {"ok": True, "jornada": nxt, "breakdown": breakdown,
            "done": league.current_jornada >= league.max_jornada}


def standings(session: Session, league: FantasyLeague) -> list[dict]:
    prices = price_map(session, league)
    members = session.exec(select(FantasyMember).where(FantasyMember.league_id == league.id)).all()
    rows = []
    for m in members:
        picks = picks_of(session, m.id)
        value = round(sum(prices.get(p.player_id, 0.0) for p in picks), 1)
        rows.append({
            "member_id": m.id, "user_id": m.user_id, "manager": m.manager_name,
            "total_points": m.total_points, "budget_remaining": m.budget_remaining,
            "squad_value": value, "worth": round(value + m.budget_remaining, 1),
            "squad_count": len(picks),
        })
    rows.sort(key=lambda r: (-r["total_points"], -r["worth"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def my_squad(session: Session, league: FantasyLeague, member: FantasyMember) -> list[dict]:
    prices = price_map(session, league)
    conf = conference_games(session, league.competition, league.grupo, league.season)
    info = {r["player_id"]: r for r in all_priced(session, league)}
    out = []
    now = utcnow()
    for p in picks_of(session, member.id):
        d = conf.get(p.player_id, {})
        extra = info.get(p.player_id, {})
        cur = prices.get(p.player_id, p.buy_price)
        locked = bool(p.clause_locked_until and now < p.clause_locked_until)
        out.append({
            "player_id": p.player_id, "name": d.get("name", "?"), "feb_code": d.get("feb_code"),
            "team": d.get("team"), "buy_price": p.buy_price, "price": cur,
            "delta": round(cur - p.buy_price, 1), "starter": p.starter,
            "val_avg": extra.get("val_avg", 0), "form": extra.get("form", 0),
            "clause": p.clause, "clause_locked": locked,
            "clause_lock_mins": int((p.clause_locked_until - now).total_seconds() // 60) if locked else 0,
        })
    out.sort(key=lambda r: (not r["starter"], -r["price"]))
    return out


def feed(session: Session, league_id: int, limit: int = 40) -> list[dict]:
    rows = session.exec(select(FantasyEvent).where(FantasyEvent.league_id == league_id)
                        .order_by(FantasyEvent.id.desc()).limit(limit)).all()
    return [{"id": e.id, "kind": e.kind, "text": e.text,
             "at": e.created_at.isoformat() + "Z"} for e in rows]


def league_out(league: FantasyLeague) -> dict:
    return {
        "id": league.id, "name": league.name, "join_code": league.join_code,
        "owner_user_id": league.owner_user_id, "competition": league.competition,
        "grupo": league.grupo, "season": league.season, "budget": league.budget,
        "squad_size": league.squad_size, "lineup_size": league.lineup_size,
        "win_bonus": league.win_bonus, "start_jornada": league.start_jornada,
        "current_jornada": league.current_jornada, "max_jornada": league.max_jornada,
        "market_weekday": league.market_weekday, "market_hour": league.market_hour,
        "market_weekday_name": WEEKDAYS[league.market_weekday],
        "market_duration_h": league.market_duration_h, "market_size": league.market_size,
        "market_open": league.market_open, "market_round": league.market_round,
        "market_opens_at": league.market_opens_at.isoformat() + "Z" if league.market_opens_at else None,
        "market_closes_at": league.market_closes_at.isoformat() + "Z" if league.market_closes_at else None,
        "clause_factor": league.clause_factor, "clause_lock_h": league.clause_lock_h,
        "clause_raise_cost": league.clause_raise_cost,
    }
