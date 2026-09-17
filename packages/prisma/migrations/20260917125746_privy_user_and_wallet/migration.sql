/*
  Warnings:

  - You are about to drop the column `emailVerified` on the `user` table. All the data in the column will be lost.
  - You are about to drop the `account` table. If the table is not empty, all the data it contains will be lost.
  - You are about to drop the `session` table. If the table is not empty, all the data it contains will be lost.
  - You are about to drop the `verification` table. If the table is not empty, all the data it contains will be lost.
  - A unique constraint covering the columns `[privyDid]` on the table `user` will be added. If there are existing duplicate values, this will fail.
  - Added the required column `privyDid` to the `user` table without a default value. This is not possible if the table is not empty.

*/
-- DropForeignKey
ALTER TABLE "account" DROP CONSTRAINT "account_userId_fkey";

-- DropForeignKey
ALTER TABLE "session" DROP CONSTRAINT "session_userId_fkey";

-- AlterTable
ALTER TABLE "user" DROP COLUMN "emailVerified",
ADD COLUMN     "privyDid" TEXT NOT NULL,
ALTER COLUMN "name" DROP NOT NULL,
ALTER COLUMN "email" DROP NOT NULL;

-- DropTable
DROP TABLE "account";

-- DropTable
DROP TABLE "session";

-- DropTable
DROP TABLE "verification";

-- CreateTable
CREATE TABLE "wallet" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" TEXT NOT NULL,
    "address" TEXT NOT NULL,
    "chain_type" TEXT NOT NULL,
    "wallet_client" TEXT NOT NULL,
    "privy_wallet_id" TEXT,
    "first_verified_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "wallet_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "wallet_user_id_idx" ON "wallet"("user_id");

-- CreateIndex
CREATE UNIQUE INDEX "wallet_chain_type_address_key" ON "wallet"("chain_type", "address");

-- CreateIndex
CREATE UNIQUE INDEX "user_privyDid_key" ON "user"("privyDid");

-- AddForeignKey
ALTER TABLE "wallet" ADD CONSTRAINT "wallet_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "user"("id") ON DELETE CASCADE ON UPDATE CASCADE;
