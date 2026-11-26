const { app, BrowserWindow, dialog, session } = require("electron");
const path = require("node:path");

const origin = "https://mockroom.dynv6.net";
const icon = app.isPackaged
  ? path.join(process.resourcesPath, "mockroom.ico")
  : path.join(__dirname, "..", "web", "mockroom.ico");

function isMockroom(url) {
  return URL.canParse(url) && new URL(url).origin === origin;
}

function configurePermissions(window) {
  let microphoneAllowed = false;
  const webSession = window.webContents.session;

  webSession.setPermissionCheckHandler((contents, permission, requestingOrigin, details) => (
    contents === window.webContents && permission === "media" && details.isMainFrame &&
    details.mediaType === "audio" && isMockroom(requestingOrigin) && microphoneAllowed
  ));

  webSession.setPermissionRequestHandler(async (contents, permission, reply, details) => {
    if (contents !== window.webContents || permission !== "media" || !details.isMainFrame ||
        !isMockroom(details.requestingUrl) || details.mediaTypes?.length !== 1 ||
        details.mediaTypes[0] !== "audio") {
      reply(false);
      return;
    }

    if (!microphoneAllowed) {
      const { response } = await dialog.showMessageBox(window, {
        type: "question",
        title: "Доступ к микрофону",
        message: "Разрешить Mockroom использовать микрофон для голосовой тренировки?",
        buttons: ["Запретить", "Разрешить"],
        defaultId: 0,
        cancelId: 0,
      });
      microphoneAllowed = response === 1;
    }
    reply(microphoneAllowed);
  });
}

async function openMockroom(window) {
  try {
    await window.loadURL(origin);
  } catch {
    if (window.isDestroyed()) return;
    const { response } = await dialog.showMessageBox(window, {
      type: "error",
      title: "Mockroom",
      icon,
      message: "Не удалось открыть Mockroom",
      detail: "Проверь подключение к интернету и повтори попытку.",
      buttons: ["Повторить", "Закрыть"],
      defaultId: 0,
      cancelId: 1,
    });
    if (window.isDestroyed()) return;
    if (response === 0) await openMockroom(window);
    else window.close();
  }
}

app.setAppUserModelId("net.dynv6.mockroom");
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.whenReady().then(() => {
    const window = new BrowserWindow({
      title: "Mockroom",
      width: 1320,
      height: 900,
      minWidth: 780,
      minHeight: 550,
      autoHideMenuBar: true,
      backgroundColor: "#101017",
      webPreferences: {
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    });
    configurePermissions(window);

    const limitNavigation = (event) => {
      if (!isMockroom(event.url)) event.preventDefault();
    };
    window.webContents.on("will-frame-navigate", limitNavigation);
    window.webContents.on("will-redirect", limitNavigation);
    window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    session.defaultSession.on("will-download", (event) => event.preventDefault());

    app.on("second-instance", () => {
      if (window.isDestroyed()) return;
      if (window.isMinimized()) window.restore();
      window.focus();
    });
    void openMockroom(window);
  });
  app.on("window-all-closed", () => app.quit());
}
