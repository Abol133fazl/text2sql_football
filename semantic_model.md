# Football DB — Semantic Model & Domain Conventions

**Iran Persian Gulf Pro League, season 2026-27 (1405-06)**
Source: varzesh3.com public API, snapshot taken 2026-11-01 (after matchweek 11).
Engine: SQLite. Open it **read-only** (`file:football.db?mode=ro`).

| Metric / Entity | Value |
|---|---|
| Teams | 18 |
| Matches | 306 (34 matchweeks × 9) — 95 finished, 1 awarded, 3 cancelled, 207 scheduled |
| Players | 531 (names in Persian only) |
| Referees / Coaches / Stadiums | Persian names only |
| Teams | English (`name`) and Persian (`name_fa`) |

---

## 1. Football Language to Schema Mapping

| Concept / Query Term | Table & Column Mapping |
|---|---|
| League table / Standings / جدول | View `v_standings` (`team`, `played`, `won`, `drawn`, `lost`, `goals_for`, `goals_against`, `goal_diff`, `points`) |
| Top of table / Leader / صدرنشین | `v_standings` sorted by `points DESC, goal_diff DESC, goals_for DESC LIMIT 1`. Standard projection must include: `team, played, points, goal_diff`. |
| Finished matches / بازی‌های انجام شده | `match.status = 'finished'`. (Exclude 'scheduled', 'cancelled', and 'awarded'). |
| Match details / Results | `v_match` (contains `round`, `match_date`, `home_team`, `away_team`, `home_goals`, `away_goals`). For derbies, check both directions: `((home_team = 'A' AND away_team = 'B') OR (home_team = 'B' AND away_team = 'A'))`. |
| Goalscorer stats / گلزنان | `goal` joined with `player p ON p.player_id = g.player_id` and `team t ON t.team_id = g.scorer_team_id`. Filter regular goals with `g.is_own_goal = 0`. |
| Own goals / گل به خودی | `goal.is_own_goal = 1`. Benefited team is `goal.team_id`; scorer's club is `goal.scorer_team_id`. Standard projection for own goal lists: `m.match_id, p.name_fa AS scorer, st.name AS scorer_team, bt.name AS benefited_team, g.minute, g.added_time`. Ordered by `m.match_id ASC`. |
| Red cards / اخراج | `card.card_type IN ('red', 'second_yellow')`. Team is `card.team_id`. |
| Yellow cards / کارت زرد | `card.card_type = 'yellow'`. To link with referee, join `match m ON m.match_id = c.match_id` then `referee r ON r.referee_id = m.referee_id`. |
| Penalties / پنالتی | Table `penalty`. Total awarded is `COUNT(*)`. Total scored/converted is `SUM(outcome = 'scored')`. |
| Goalkeeper Clean Sheets | Starters only (`l.position = 'GK' AND l.is_starter = 1`) in finished games (`m.status = 'finished'`). Must join `v_team_match tm ON tm.match_id = l.match_id AND tm.team_id = l.team_id` with `tm.goals_against = 0`. |
| Coaching changes / تغییر سرمربی | Teams having `COUNT(DISTINCT coach_id) > 1` in `match_coach`. Group by `mc.team_id, mc.coach_id` to list each tenure with: `t.name AS team, c.name_fa AS coach, MIN(m.round) AS first_round, MAX(m.round) AS last_round, COUNT(*) AS matches`. Joined with `match m` to access `m.round`. |
| Late goals / گل دقایق پایانی | Goals after 75th minute: `g.half = 'second_half' AND g.minute >= 76` (or `g.minute > 75`). |
| Formations / آرایش‌های بازی | Formations are recorded in `match.home_formation` and `match.away_formation`. When analyzing a team or coach, use: `CASE WHEN m.home_team_id = mc.team_id THEN m.home_formation ELSE m.away_formation END`. Only finished matches (`m.status = 'finished'`). |
| Minutes played / دقایق بازی | View `v_player_minutes` (`minutes_played`). Always join `player p` and `team t`. |
| VAR decisions / داور ویدیویی | Table `var_decision` grouped by `decision`, ordered by `COUNT(*) DESC`. |

---

## 2. Standard Analytics & Projection Conventions

1. **Entity + Team Context Rule**:
   - Whenever reporting stats for individual **players** or **coaches**, ALWAYS include their club/team name (`t.name`) in the projection.
   - Example player projections: `p.name_fa AS player, t.name AS team, [metric]`
   - Example coach projections: `c.name_fa AS coach, t.name AS team, [metric]`

2. **Standard Ranking Limits (When No Specific Number is Given)**:
   - **Podium Rule (Top 3)**: Superlative questions about **teams, coaches, or referees** (e.g. "Which referee showed the most cards?", "Best home team?", "Which coach used the most formations?", "Which team scores most late goals?") represent the league podium and must use `LIMIT 3`.
   - **Top 5 Rule**: Superlative questions about **players** (e.g. "Top scorers?", "Which goalkeepers have the most clean sheets?", "Which player played the most minutes?") must use `LIMIT 5`.
   - **Single Leader**: "Who is top of the table / صدرنشین" refers strictly to 1 team: `LIMIT 1`.
   - **Full Rankings**: Disciplinary summaries (e.g. red cards received by teams across the league) or event breakdowns (VAR decisions) include all participating teams/categories (do NOT apply LIMIT unless explicitly requested).

3. **Deterministic Tie-Breaking**:
   - SQLite orders tied values arbitrarily unless a secondary key is provided.
   - For all leaderboards, ALWAYS append the entity name as an alphabetical tie-breaker:
     `ORDER BY metric DESC, entity_name ASC`
   - For standings tie-break:
     `ORDER BY points DESC, goal_diff DESC, goals_for DESC`
   - For chronological/match listings (like own goals):
     `ORDER BY m.match_id ASC`