using System.Windows;
using System.Windows.Input;

namespace ToyLims.StandardClient;

public partial class PromptWindow : Window
{
    private PromptWindow(string title, string message, string confirmText, bool canCancel)
    {
        InitializeComponent();
        TitleText.Text = title;
        MessageText.Text = message;
        ConfirmButton.Content = confirmText;
        CancelButton.Visibility = canCancel ? Visibility.Visible : Visibility.Collapsed;
    }

    public static bool Confirm(Window owner, string title, string message, string confirmText = "确认")
    {
        var dialog = new PromptWindow(title, message, confirmText, true) { Owner = owner };
        return dialog.ShowDialog() == true;
    }

    public static void ShowInfo(Window owner, string title, string message)
    {
        var dialog = new PromptWindow(title, message, "知道了", false) { Owner = owner };
        dialog.ShowDialog();
    }

    private void Confirm_Click(object sender, RoutedEventArgs e) => DialogResult = true;
    private void Cancel_Click(object sender, RoutedEventArgs e) => DialogResult = false;

    private void Header_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ButtonState == MouseButtonState.Pressed) DragMove();
    }
}
