-- AlterTable
ALTER TABLE "simulation" ADD COLUMN     "fills_synced_to" TEXT;

-- CreateTable
CREATE TABLE "account_fill" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "account_id" TEXT NOT NULL,
    "trade_id" TEXT NOT NULL,
    "client_order_id" TEXT NOT NULL,
    "side" TEXT NOT NULL,
    "quantity" DECIMAL(38,18) NOT NULL,
    "price" DECIMAL(38,18) NOT NULL,
    "commission" DECIMAL(38,18) NOT NULL,
    "commission_currency" TEXT NOT NULL,
    "filled_at" TIMESTAMP(3) NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "account_fill_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "account_fill_account_id_filled_at_idx" ON "account_fill"("account_id", "filled_at");

-- CreateIndex
CREATE UNIQUE INDEX "account_fill_account_id_trade_id_key" ON "account_fill"("account_id", "trade_id");

-- AddForeignKey
ALTER TABLE "account_fill" ADD CONSTRAINT "account_fill_account_id_fkey" FOREIGN KEY ("account_id") REFERENCES "simulation"("account_id") ON DELETE CASCADE ON UPDATE CASCADE;

