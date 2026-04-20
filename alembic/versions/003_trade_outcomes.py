"""trade_outcomes + agent_contributions + correlation_snapshots (Week 2)

Revision ID: 003
Revises: 002
Create Date: 2026-04-20 00:00:00.000000

Schema source: trading-floor-plan/schemas/postgres-outcomes.sql

Notes:
- trade_outcomes is immutable (trigger-enforced, like agent_episodes).
- agent_contributions has counterfactual_hit + attributed_pnl_usd populated
  by the nightly job; null until computed.
- correlation_snapshots is a regular table (not hypertable) — weekly insert
  cadence is small, access pattern is point queries.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE trade_outcomes (
            trade_id            UUID PRIMARY KEY,
            cycle_id            UUID NOT NULL,
            symbol              TEXT NOT NULL,
            venue               TEXT NOT NULL,

            entry_ts            TIMESTAMPTZ NOT NULL,
            exit_ts             TIMESTAMPTZ NOT NULL,
            holding_period_s    INTEGER GENERATED ALWAYS AS
                (EXTRACT(EPOCH FROM (exit_ts - entry_ts))::INTEGER) STORED,

            direction           TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
            entry_price         NUMERIC(20, 8) NOT NULL,
            exit_price          NUMERIC(20, 8) NOT NULL,
            quantity            NUMERIC(20, 8) NOT NULL,

            pnl_usd             NUMERIC(20, 8) NOT NULL,
            pnl_pct             NUMERIC(10, 6) NOT NULL,
            costs_usd           NUMERIC(20, 8) NOT NULL DEFAULT 0,
            net_pnl_usd         NUMERIC(20, 8) GENERATED ALWAYS AS
                (pnl_usd - costs_usd) STORED,

            exit_reason         TEXT NOT NULL CHECK (exit_reason IN
                ('stop', 'target', 'kill_switch', 'manual', 'trailing_stop', 'time_exit', 'veto')),
            regime_at_entry     TEXT NOT NULL,
            regime_at_exit      TEXT NOT NULL,

            backfilled          BOOLEAN NOT NULL DEFAULT false,

            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT exit_after_entry CHECK (exit_ts > entry_ts),
            CONSTRAINT quantity_positive CHECK (quantity > 0),
            CONSTRAINT pnl_pct_reasonable CHECK (pnl_pct BETWEEN -1 AND 10)
        );
        """
    )

    op.execute("CREATE INDEX idx_outcomes_cycle ON trade_outcomes (cycle_id);")
    op.execute(
        "CREATE INDEX idx_outcomes_symbol_exit ON trade_outcomes (symbol, exit_ts DESC);"
    )
    op.execute(
        "CREATE INDEX idx_outcomes_regime_entry ON trade_outcomes (regime_at_entry, exit_ts DESC);"
    )
    op.execute(
        "CREATE INDEX idx_outcomes_regime_exit ON trade_outcomes (regime_at_exit, exit_ts DESC);"
    )
    op.execute("CREATE INDEX idx_outcomes_exit_reason ON trade_outcomes (exit_reason);")
    op.execute("CREATE INDEX idx_outcomes_ts ON trade_outcomes (exit_ts DESC);")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_outcome_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            IF current_user = 'migration_admin' THEN
                RETURN COALESCE(NEW, OLD);
            END IF;
            RAISE EXCEPTION
                'trade_outcomes is immutable. Operation: %, User: %',
                TG_OP, current_user;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER outcomes_reject_update
            BEFORE UPDATE ON trade_outcomes
            FOR EACH ROW EXECUTE FUNCTION reject_outcome_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER outcomes_reject_delete
            BEFORE DELETE ON trade_outcomes
            FOR EACH ROW EXECUTE FUNCTION reject_outcome_mutation();
        """
    )

    op.execute(
        """
        CREATE TABLE agent_contributions (
            contribution_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            trade_id            UUID NOT NULL REFERENCES trade_outcomes(trade_id),
            cycle_id            UUID NOT NULL,
            agent_id            TEXT NOT NULL,
            agent_version       TEXT NOT NULL,

            signal_direction    TEXT NOT NULL CHECK (signal_direction IN ('LONG', 'SHORT', 'NEUTRAL')),
            signal_confidence   NUMERIC(5, 4) NOT NULL CHECK (signal_confidence BETWEEN 0 AND 1),
            reasoning           TEXT,

            matched_trade_direction BOOLEAN NOT NULL,

            counterfactual_hit  BOOLEAN,
            attributed_pnl_usd  NUMERIC(20, 8),
            counterfactual_computed_at TIMESTAMPTZ,

            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            UNIQUE (trade_id, agent_id, agent_version)
        );
        """
    )
    op.execute("CREATE INDEX idx_contributions_trade ON agent_contributions (trade_id);")
    op.execute(
        "CREATE INDEX idx_contributions_agent ON agent_contributions (agent_id, created_at DESC);"
    )
    op.execute(
        "CREATE INDEX idx_contributions_agent_version ON agent_contributions (agent_version);"
    )
    op.execute(
        "CREATE INDEX idx_contributions_pending_cf ON agent_contributions (created_at) "
        "WHERE counterfactual_hit IS NULL;"
    )

    op.execute(
        """
        CREATE TABLE correlation_snapshots (
            snapshot_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            window_days         INTEGER NOT NULL DEFAULT 60,
            symbols             TEXT[] NOT NULL,
            matrix              JSONB NOT NULL,
            method              TEXT NOT NULL DEFAULT 'pearson'
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_correlation_computed ON correlation_snapshots (computed_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS correlation_snapshots;")
    op.execute("DROP TABLE IF EXISTS agent_contributions;")
    op.execute("DROP TRIGGER IF EXISTS outcomes_reject_delete ON trade_outcomes;")
    op.execute("DROP TRIGGER IF EXISTS outcomes_reject_update ON trade_outcomes;")
    op.execute("DROP FUNCTION IF EXISTS reject_outcome_mutation();")
    op.execute("DROP TABLE IF EXISTS trade_outcomes;")
