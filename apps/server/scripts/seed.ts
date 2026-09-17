import { prisma } from "@/src/lib/prisma.js";

async function main() {
  // No seed data yet — chat-domain seeds will be added in a later phase.
  console.log("🌱 Nothing to seed yet.");
}

main()
  .catch((error) => {
    console.error(error);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
