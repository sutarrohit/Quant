-- CreateTable
CREATE TABLE "strategy" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "archived_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "strategy_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "strategy_version" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "strategy_id" UUID NOT NULL,
    "version" INTEGER NOT NULL,
    "spec" JSONB NOT NULL,
    "spec_hash" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "strategy_version_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "backtest_run" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" TEXT NOT NULL,
    "version_id" UUID NOT NULL,
    "request_id" TEXT NOT NULL,
    "job_id" TEXT,
    "status" TEXT NOT NULL,
    "venue" TEXT NOT NULL,
    "instrument_id" TEXT NOT NULL,
    "bar_type" TEXT NOT NULL,
    "window_start" TIMESTAMP(3) NOT NULL,
    "window_end" TIMESTAMP(3) NOT NULL,
    "starting_balances" TEXT[],
    "maker_bps" DECIMAL(38,18) NOT NULL,
    "taker_bps" DECIMAL(38,18) NOT NULL,
    "slippage_bps" DECIMAL(38,18) NOT NULL,
    "summary" JSONB,
    "error_code" TEXT,
    "error_message" TEXT,
    "submitted_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "finished_at" TIMESTAMP(3),

    CONSTRAINT "backtest_run_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "simulation" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" TEXT NOT NULL,
    "version_id" UUID NOT NULL,
    "account_id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "venue" TEXT NOT NULL,
    "instrument_id" TEXT NOT NULL,
    "bar_type" TEXT NOT NULL,
    "maker_bps" DECIMAL(38,18) NOT NULL,
    "taker_bps" DECIMAL(38,18) NOT NULL,
    "slippage_bps" DECIMAL(38,18) NOT NULL,
    "risk_limits" JSONB,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "simulation_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "strategy_user_id_idx" ON "strategy"("user_id");

-- CreateIndex
CREATE UNIQUE INDEX "strategy_version_strategy_id_version_key" ON "strategy_version"("strategy_id", "version");

-- CreateIndex
CREATE UNIQUE INDEX "backtest_run_request_id_key" ON "backtest_run"("request_id");

-- CreateIndex
CREATE INDEX "backtest_run_user_id_submitted_at_idx" ON "backtest_run"("user_id", "submitted_at");

-- CreateIndex
CREATE UNIQUE INDEX "simulation_account_id_key" ON "simulation"("account_id");

-- CreateIndex
CREATE INDEX "simulation_user_id_idx" ON "simulation"("user_id");

-- AddForeignKey
ALTER TABLE "strategy" ADD CONSTRAINT "strategy_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "user"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "strategy_version" ADD CONSTRAINT "strategy_version_strategy_id_fkey" FOREIGN KEY ("strategy_id") REFERENCES "strategy"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "backtest_run" ADD CONSTRAINT "backtest_run_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "user"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "backtest_run" ADD CONSTRAINT "backtest_run_version_id_fkey" FOREIGN KEY ("version_id") REFERENCES "strategy_version"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "simulation" ADD CONSTRAINT "simulation_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "user"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "simulation" ADD CONSTRAINT "simulation_version_id_fkey" FOREIGN KEY ("version_id") REFERENCES "strategy_version"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
