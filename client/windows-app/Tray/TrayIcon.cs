using System.Windows.Forms;
using Microsoft.UI.Dispatching;
using NebulaCommanderApp.Services;

namespace NebulaCommanderApp.Tray;

/// <summary>
/// The app's tray presence. WinUI 3 has no first-party tray icon API;
/// System.Windows.Forms.NotifyIcon (enabled via UseWindowsForms in the csproj)
/// is the standard, well-supported way to get one in a WinUI 3 desktop app -
/// it just needs *some* Win32 message loop pumping on this thread, which the
/// WinUI 3 DispatcherQueue already provides, so no separate
/// System.Windows.Forms.Application.Run() is needed.
/// </summary>
public sealed class TrayIcon : IDisposable
{
    private readonly NotifyIcon _notifyIcon;
    private readonly System.Threading.Timer _tooltipTimer;
    private readonly DispatcherQueue _dispatcherQueue;

    public TrayIcon(Action onOpen, Action onExit)
    {
        // Captured on the UI thread (constructed from MainWindow's constructor) so
        // the timer callback below - which runs on a thread-pool thread - can marshal
        // the NotifyIcon.Text update back instead of touching it cross-thread.
        _dispatcherQueue = DispatcherQueue.GetForCurrentThread();

        var contextMenu = new ContextMenuStrip();
        var openItem = new ToolStripMenuItem("Open Nebula Commander", null, (_, _) => onOpen())
        {
            Font = new System.Drawing.Font(contextMenu.Font, System.Drawing.FontStyle.Bold),
        };
        contextMenu.Items.Add(openItem);
        contextMenu.Items.Add(new ToolStripSeparator());
        contextMenu.Items.Add("Exit", null, (_, _) => onExit());

        var iconPath = Path.Combine(AppContext.BaseDirectory, "Assets", "AppIcon.ico");

        _notifyIcon = new NotifyIcon
        {
            Icon = File.Exists(iconPath)
                ? new System.Drawing.Icon(iconPath)
                : System.Drawing.SystemIcons.Application,
            Text = "Nebula Commander",
            Visible = true,
            ContextMenuStrip = contextMenu,
        };
        _notifyIcon.MouseClick += (_, e) =>
        {
            if (e.Button == MouseButtons.Left)
            {
                onOpen();
            }
        };

        // Best-effort tooltip refresh from the service's self-reported status -
        // independent of the main window's own UI/polling, so the tray still
        // reflects reality while the window is hidden.
        _tooltipTimer = new System.Threading.Timer(_ => RefreshTooltip(), null, TimeSpan.Zero, TimeSpan.FromSeconds(5));
    }

    private void RefreshTooltip()
    {
        try
        {
            var status = StatusStore.Load();
            var text = $"Nebula Commander - {status.Message}";
            // NotifyIcon.Text has a hard 127-char limit (throws ArgumentException past it).
            var truncated = text.Length > 127 ? text[..127] : text;
            _dispatcherQueue.TryEnqueue(() => _notifyIcon.Text = truncated);
        }
        catch
        {
            // Tooltip is best-effort; never let a refresh failure surface anywhere.
        }
    }

    public void Dispose()
    {
        _tooltipTimer.Dispose();
        _notifyIcon.Visible = false;
        _notifyIcon.Dispose();
    }
}
