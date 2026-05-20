const { create, ev } = require("@open-wa/wa-automate");

const CHROME_USER_AGENT =
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

ev.on("**.**", (data, sessionId, namespace) => {
  console.log(`[event] ${namespace}.${sessionId}`, data);
});

async function main() {
  const client = await create({
    sessionId: "inboxsignal",

    useChrome: true,
    executablePath: "/usr/bin/google-chrome",
    customUserAgent: CHROME_USER_AGENT,

    headless: false,
    useStealth: true,

    qrTimeout: 0,
    authTimeout: 0,
    waitForRipeSessionTimeout: 0,

    cacheEnabled: false,
    skipUpdateCheck: true,

    viewport: {
      width: 1440,
      height: 900,
    },

    chromiumArgs: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--disable-extensions",
      "--window-size=1440,900",
      `--user-agent=${CHROME_USER_AGENT}`,
    ],
  });

  console.log("OpenWA client is ready");

  client.onMessage(async (message) => {
    if (message.fromMe || message.local) {
      return;
    }

    console.log("Incoming message:", {
      id: message.id,
      mId: message.mId,
      from: message.from,
      chatId: message.chatId,
      senderId: message.senderId,
      notifyName: message.notifyName,
      body: message.body,
      type: message.type,
      timestamp: message.timestamp,
    });
  });
}

main().catch((error) => {
  console.error("OpenWA startup failed:", error);
  process.exit(1);
});