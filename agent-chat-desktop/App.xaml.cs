using System.IO;
using System.Windows;

namespace AgentChat.Desktop;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        if (e.Args.Any(arg => string.Equals(arg, "--smoke", StringComparison.OrdinalIgnoreCase)))
        {
            var paths = AppPaths.Find();
            paths.Ensure();
            var agents = new AgentConfigLoader(paths).LoadAgents();
            var conversations = new ChatStore(paths).Load();
            File.WriteAllText(
                Path.Combine(paths.AppDataDir, "smoke.ok"),
                $"agents={agents.Count}; conversations={conversations.Count}; {DateTimeOffset.Now:O}");
            Shutdown(0);
            return;
        }

        new MainWindow().Show();
    }
}
