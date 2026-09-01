using System.Windows;
using System.Windows.Input;

namespace ToyLims.StandardClient;

public partial class LoginWindow : Window
{
    public string Password => PasswordBox.Password;

    public LoginWindow(string error = "")
    {
        InitializeComponent();
        ErrorText.Text = error;
        Loaded += (_, _) => PasswordBox.Focus();
    }

    private void Login_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrEmpty(PasswordBox.Password))
        {
            ErrorText.Text = "请输入用户密码";
            return;
        }
        DialogResult = true;
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => DialogResult = false;
    private void PasswordBox_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter) Login_Click(sender, e);
    }
}
