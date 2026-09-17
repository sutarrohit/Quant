-- CreateTable
CREATE TABLE "user" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "emailVerified" BOOLEAN NOT NULL DEFAULT false,
    "image" TEXT,
    "onboardingCompletedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "user_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "session" (
    "id" TEXT NOT NULL,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "token" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "ipAddress" TEXT,
    "userAgent" TEXT,
    "userId" TEXT NOT NULL,

    CONSTRAINT "session_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "account" (
    "id" TEXT NOT NULL,
    "accountId" TEXT NOT NULL,
    "providerId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "accessToken" TEXT,
    "refreshToken" TEXT,
    "idToken" TEXT,
    "accessTokenExpiresAt" TIMESTAMP(3),
    "refreshTokenExpiresAt" TIMESTAMP(3),
    "scope" TEXT,
    "password" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "account_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "verification" (
    "id" TEXT NOT NULL,
    "identifier" TEXT NOT NULL,
    "value" TEXT NOT NULL,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "verification_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "trials" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "strategy_lineage_id" TEXT NOT NULL,
    "params_hash" TEXT NOT NULL,
    "objective" TEXT NOT NULL,
    "ran_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "was_oos" BOOLEAN NOT NULL,
    "status" TEXT NOT NULL,
    "error_message" TEXT,

    CONSTRAINT "trials_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "snapshot_capture" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "capture_date" DATE NOT NULL,
    "captured_at" TIMESTAMP(3) NOT NULL,
    "payload_sha256" TEXT NOT NULL,
    "expected_symbol_count" INTEGER NOT NULL,
    "actual_symbol_count" INTEGER NOT NULL,
    "status" TEXT NOT NULL,

    CONSTRAINT "snapshot_capture_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "symbol_listing_snapshot" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "capture_id" UUID NOT NULL,
    "raw_payload" BYTEA NOT NULL,
    "symbol" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "base_asset" TEXT NOT NULL,
    "quote_asset" TEXT NOT NULL,
    "tick_size" DECIMAL(38,18) NOT NULL,
    "step_size" DECIMAL(38,18) NOT NULL,
    "min_notional" DECIMAL(38,18),
    "captured_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "symbol_listing_snapshot_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "user_email_key" ON "user"("email");

-- CreateIndex
CREATE INDEX "session_userId_idx" ON "session"("userId");

-- CreateIndex
CREATE UNIQUE INDEX "session_token_key" ON "session"("token");

-- CreateIndex
CREATE INDEX "account_userId_idx" ON "account"("userId");

-- CreateIndex
CREATE INDEX "verification_identifier_idx" ON "verification"("identifier");

-- CreateIndex
CREATE INDEX "trials_strategy_lineage_id_idx" ON "trials"("strategy_lineage_id");

-- CreateIndex
CREATE INDEX "trials_params_hash_idx" ON "trials"("params_hash");

-- CreateIndex
CREATE INDEX "snapshot_capture_capture_date_idx" ON "snapshot_capture"("capture_date");

-- CreateIndex
CREATE INDEX "symbol_listing_snapshot_captured_at_idx" ON "symbol_listing_snapshot"("captured_at");

-- CreateIndex
CREATE INDEX "symbol_listing_snapshot_symbol_captured_at_idx" ON "symbol_listing_snapshot"("symbol", "captured_at");

-- CreateIndex
CREATE INDEX "symbol_listing_snapshot_capture_id_idx" ON "symbol_listing_snapshot"("capture_id");

-- AddForeignKey
ALTER TABLE "session" ADD CONSTRAINT "session_userId_fkey" FOREIGN KEY ("userId") REFERENCES "user"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "account" ADD CONSTRAINT "account_userId_fkey" FOREIGN KEY ("userId") REFERENCES "user"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "symbol_listing_snapshot" ADD CONSTRAINT "symbol_listing_snapshot_capture_id_fkey" FOREIGN KEY ("capture_id") REFERENCES "snapshot_capture"("id") ON DELETE CASCADE ON UPDATE CASCADE;
