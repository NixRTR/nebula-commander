using System.Diagnostics;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace NebulaCommanderApp.Controls;

public sealed partial class CloudPromo : UserControl
{
    private const string PricingUrl = "https://cloud.nebulacdr.net/pricing";

    private static readonly SolidColorBrush PillBrush = new(Color.FromArgb(0xFF, 0xD0, 0xB8, 0x4A));
    private static readonly SolidColorBrush PillHoverBrush = new(Color.FromArgb(0xFF, 0xDF, 0xCC, 0x73));

    public CloudPromo()
    {
        InitializeComponent();
    }

    private void PromoButton_Click(object sender, RoutedEventArgs e) =>
        Process.Start(new ProcessStartInfo { FileName = PricingUrl, UseShellExecute = true });

    private void PromoButton_PointerEntered(object sender, PointerRoutedEventArgs e) => Pill.Background = PillHoverBrush;

    private void PromoButton_PointerExited(object sender, PointerRoutedEventArgs e) => Pill.Background = PillBrush;
}
