// AgentChat/coding_agent 2026-07-08: animated pixel office showing every agent at a desk.
// Pure vector "pixel art" drawn in OnRender - no image assets, crisp at any scale.
using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;

namespace AgentChat.Desktop;

public sealed class PixelOfficeControl : FrameworkElement
{
    public sealed record OfficeAgent(string Name, string State, bool Selected);

    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromMilliseconds(160) };
    private int _frame;
    private IReadOnlyList<OfficeAgent> _agents = Array.Empty<OfficeAgent>();

    private static readonly Brush Floor = Frozen("#0B1522");
    private static readonly Brush FloorLine = Frozen("#12233A");
    private static readonly Brush Wall = Frozen("#101E31");
    private static readonly Brush WallTrim = Frozen("#1A2E4A");
    private static readonly Brush WindowGlow = Frozen("#14293F");
    private static readonly Brush Star = Frozen("#3A5E86");
    private static readonly Brush DeskWood = Frozen("#39537A");
    private static readonly Brush DeskEdge = Frozen("#22385C");
    private static readonly Brush MonitorShell = Frozen("#1B2A44");
    private static readonly Brush ScreenOff = Frozen("#0A1220");
    private static readonly Brush ScreenOn = Frozen("#103A31");
    private static readonly Brush ScreenCode = Frozen("#2CE6A0");
    private static readonly Brush ScreenCodeDim = Frozen("#1B8F66");
    private static readonly Brush ScreenRed = Frozen("#57131F");
    private static readonly Brush ScreenRedGlow = Frozen("#FF4D6D");
    private static readonly Brush ScreenBlue = Frozen("#0F2C4A");
    private static readonly Brush ScreenBlueGlow = Frozen("#22D3EE");
    private static readonly Brush Chair = Frozen("#16233A");
    private static readonly Brush Skin = Frozen("#E8B98A");
    private static readonly Brush Hair = Frozen("#2B2B33");
    private static readonly Brush Shirt = Frozen("#3E7BD6");
    private static readonly Brush Shirt2 = Frozen("#7C5CD6");
    private static readonly Brush Shirt3 = Frozen("#2CB6A0");
    private static readonly Brush Shirt4 = Frozen("#D68A3E");
    private static readonly Brush Coffee = Frozen("#7A4A2B");
    private static readonly Brush Steam = Frozen("#5E7Fa6");
    private static readonly Brush Amber = Frozen("#F5B942");
    private static readonly Brush Red = Frozen("#FF4D6D");
    private static readonly Brush Green = Frozen("#24F2B4");
    private static readonly Brush Cyan = Frozen("#22D3EE");
    private static readonly Brush Purple = Frozen("#8B5CF6");
    private static readonly Brush LabelDim = Frozen("#8FA9BD");
    private static readonly Brush LabelBright = Frozen("#E6F4FF");
    private static readonly Brush SelectGlow = Frozen("#332CE6A0");
    private static readonly Typeface LabelFace = new(new FontFamily("Consolas"), FontStyles.Normal, FontWeights.Bold, FontStretches.Normal);

    public PixelOfficeControl()
    {
        SnapsToDevicePixels = true;
        RenderOptions.SetEdgeMode(this, EdgeMode.Aliased);
        _timer.Tick += (_, _) =>
        {
            _frame++;
            InvalidateVisual();
        };
        Loaded += (_, _) => _timer.Start();
        Unloaded += (_, _) => _timer.Stop();
    }

    public void SetAgents(IEnumerable<OfficeAgent> agents)
    {
        _agents = agents.ToList();
        InvalidateVisual();
    }

    protected override void OnRender(DrawingContext dc)
    {
        var width = ActualWidth;
        var height = ActualHeight;
        if (width < 40 || height < 40)
        {
            return;
        }

        dc.DrawRectangle(Wall, null, new Rect(0, 0, width, height * 0.38));
        dc.DrawRectangle(WallTrim, null, new Rect(0, height * 0.36, width, height * 0.02));
        dc.DrawRectangle(Floor, null, new Rect(0, height * 0.38, width, height * 0.62));
        for (var i = 1; i < 5; i++)
        {
            dc.DrawRectangle(FloorLine, null, new Rect(0, height * (0.38 + 0.124 * i), width, 1));
        }

        // Night window with drifting stars.
        var winW = width * 0.22;
        var win = new Rect(width * 0.5 - winW / 2, height * 0.05, winW, height * 0.24);
        dc.DrawRectangle(WindowGlow, new Pen(WallTrim, 2), win);
        for (var i = 0; i < 7; i++)
        {
            var sx = win.X + ((i * 37 + _frame * 0.6) % winW);
            var sy = win.Y + (i * 29 % (win.Height - 6)) + 3;
            dc.DrawRectangle(Star, null, new Rect(sx, sy, 2, 2));
        }

        var agents = _agents;
        if (agents.Count == 0)
        {
            return;
        }

        var columns = agents.Count <= 2 ? agents.Count : (agents.Count <= 4 ? 2 : 3);
        var rows = (int)Math.Ceiling(agents.Count / (double)columns);
        var cellW = width / columns;
        var cellH = (height - height * 0.06) / rows;

        for (var index = 0; index < agents.Count; index++)
        {
            var col = index % columns;
            var row = index / columns;
            var cell = new Rect(col * cellW, height * 0.06 + row * cellH, cellW, cellH);
            DrawDeskScene(dc, agents[index], cell, index);
        }
    }

    private void DrawDeskScene(DrawingContext dc, OfficeAgent agent, Rect cell, int seat)
    {
        // Pixel grid inside the cell: 26 x 20 logical pixels.
        var p = Math.Min(cell.Width / 26, cell.Height / 20);
        var originX = cell.X + (cell.Width - p * 26) / 2;
        var originY = cell.Y + (cell.Height - p * 20) / 2;
        void Px(Brush brush, double x, double y, double w = 1, double h = 1) =>
            dc.DrawRectangle(brush, null, new Rect(originX + x * p, originY + y * p, w * p, h * p));

        var state = agent.State.ToUpperInvariant();
        var working = state == "WORKING";
        var searching = state == "SEARCHING";
        var blocked = state == "BLOCKED";
        var complete = state == "COMPLETE";
        var waiting = state == "WAITING_APPROVAL";
        var idle = !working && !searching && !blocked && !complete && !waiting;
        var beat = (_frame + seat * 3) % 4;      // desync neighbours
        var slowBeat = (_frame / 3 + seat) % 2;

        if (agent.Selected)
        {
            dc.DrawRoundedRectangle(SelectGlow, null, new Rect(cell.X + 2, cell.Y + 2, cell.Width - 4, cell.Height - 4), 6, 6);
        }

        // Chair
        Px(Chair, 10, 13, 6, 1);
        Px(Chair, 12, 14, 2, 3);
        Px(Chair, 10, 8, 1, 5);

        // Character (seen from behind-left, facing monitor)
        var bodyShirt = (seat % 4) switch { 0 => Shirt, 1 => Shirt2, 2 => Shirt3, _ => Shirt4 };
        var bob = working && beat is 1 or 3 ? -0.4 : 0;
        var celebrate = complete && slowBeat == 0 ? -1.0 : 0;
        Px(Hair, 11.5, 5.6 + bob + celebrate, 3, 1.6);                    // hair
        Px(Skin, 11.7, 7.0 + bob + celebrate, 2.6, 1.8);                  // head
        Px(bodyShirt, 11, 8.8 + bob + celebrate, 4, 3.4);                 // torso

        if (working)
        {
            // Typing arms, alternating
            Px(Skin, 14.6, beat is 0 or 2 ? 10.2 : 10.8, 2.4, 0.9);
            Px(Skin, 9.4, beat is 1 or 3 ? 10.2 : 10.8, 2.0, 0.9);
        }
        else if (complete)
        {
            // Arms up
            Px(Skin, 15, 7.4 + celebrate, 1, 2.4);
            Px(Skin, 10, 7.4 + celebrate, 1, 2.4);
        }
        else if (idle)
        {
            // Coffee sip: cup raises every other slow beat
            var cupY = slowBeat == 0 ? 8.6 : 10.4;
            Px(Skin, 14.8, cupY + 0.8, 1.6, 0.9);
            Px(Coffee, 15.4, cupY, 1.4, 1.2);
            if (slowBeat == 0)
            {
                Px(Steam, 15.8, cupY - 1.4, 0.6, 0.9);
            }
        }
        else
        {
            Px(Skin, 14.6, 10.6, 2.0, 0.9);
        }

        // Desk
        Px(DeskWood, 8, 12, 12, 1.4);
        Px(DeskEdge, 8, 13.4, 1, 3);
        Px(DeskEdge, 19, 13.4, 1, 3);

        // Monitor
        Px(MonitorShell, 15.4, 6.6, 5.2, 4.6);
        Px(MonitorShell, 17.4, 11.2, 1.2, 0.8);
        var screen = blocked ? ScreenRed : searching ? ScreenBlue : working ? ScreenOn : ScreenOff;
        Px(screen, 15.9, 7.1, 4.2, 3.6);
        if (working)
        {
            // Scrolling code lines
            for (var line = 0; line < 3; line++)
            {
                var lw = 1.4 + ((line * 2 + _frame) % 3) * 0.8;
                Px(line == (_frame % 3) ? ScreenCode : ScreenCodeDim, 16.2, 7.5 + line, lw, 0.5);
            }
        }
        else if (searching)
        {
            // Radar sweep dot
            var sweep = (_frame + seat) % 6;
            Px(ScreenBlueGlow, 16.2 + sweep * 0.6, 7.6 + (sweep % 3), 0.7, 0.7);
            Px(ScreenBlueGlow, 16.4, 9.8, 3.2, 0.4);
        }
        else if (blocked && slowBeat == 0)
        {
            Px(ScreenRedGlow, 17.4, 7.7, 1.2, 2.2); // "!" bar
            Px(ScreenRedGlow, 17.4, 10.2, 1.2, 0.5);
        }
        else if (complete)
        {
            Px(Green, 16.6, 8.8, 0.8, 0.8);
            Px(Green, 17.3, 9.5, 0.8, 0.8);
            Px(Green, 18.0, 8.8, 0.8, 0.8);
            Px(Green, 18.7, 8.1, 0.8, 0.8);
        }

        // Thought/status bubble above the head
        if (waiting)
        {
            var hop = slowBeat == 0 ? -0.6 : 0;
            Px(Amber, 12, 2.6 + hop, 2.4, 2.4);
            Px(ScreenOff, 12.9, 3.1 + hop, 0.7, 1.0);
            Px(ScreenOff, 12.9, 4.3 + hop, 0.7, 0.4);
        }
        else if (blocked && slowBeat == 0)
        {
            Px(Red, 12.4, 2.6, 1.4, 2.0);
            Px(Red, 12.4, 5.0, 1.4, 0.6);
        }
        else if (searching)
        {
            // Magnifier bobbing
            var hop = beat is 1 or 2 ? -0.4 : 0;
            Px(Purple, 12, 3.0 + hop, 2.0, 2.0);
            Px(Purple, 13.8, 4.8 + hop, 0.9, 0.9);
        }
        else if (complete)
        {
            Px(Green, 12.2, 3.0, 0.8, 0.8);
            Px(Green, 12.9, 3.7, 0.8, 0.8);
            Px(Green, 13.6, 3.0, 0.8, 0.8);
            Px(Green, 14.3, 2.3, 0.8, 0.8);
        }
        else if (idle && (_frame + seat * 5) % 14 > 11)
        {
            Px(Steam, 12.6, 3.2, 1.0, 1.0); // occasional "z"
            Px(Steam, 13.4, 2.4, 0.7, 0.7);
        }

        // Status dot + name label
        var dot = blocked ? Red : waiting ? Amber : working ? Green : searching ? Purple : complete ? Green : Cyan;
        var pulse = (working || searching) && slowBeat == 0 ? 1.4 : 1.0;
        dc.DrawEllipse(dot, null,
            new Point(originX + 4 * p, originY + 17.6 * p), 2.4 * pulse, 2.4 * pulse);
        var label = new FormattedText(
            agent.Name.ToUpperInvariant(),
            System.Globalization.CultureInfo.InvariantCulture,
            FlowDirection.LeftToRight,
            LabelFace,
            Math.Max(9, Math.Min(11.5, p * 4.4)),
            agent.Selected ? LabelBright : LabelDim,
            VisualTreeHelper.GetDpi(this).PixelsPerDip)
        {
            MaxTextWidth = Math.Max(20, cell.Width - 8 * p),
            MaxLineCount = 1,
            Trimming = TextTrimming.CharacterEllipsis,
        };
        dc.DrawText(label, new Point(originX + 5.6 * p, originY + 17.6 * p - label.Height / 2));
    }

    private static Brush Frozen(string hex)
    {
        var brush = new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));
        brush.Freeze();
        return brush;
    }
}
