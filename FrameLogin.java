import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;

import javax.swing.JButton;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JOptionPane;
import javax.swing.JPanel;
import javax.swing.JTextField;
import javax.swing.border.EmptyBorder;

public class FrameLogin extends JFrame {
	//ログイン画面
	private JPanel contentPane;

	private JLabel lblLogin = new JLabel("LOGIN");
	//id
	private JTextField textFieldId;
	private JButton btnLogin = new JButton("Login");



	/**
	 * Create the frame.
	 */
	public FrameLogin() {
		setTitle("Game");
		setLocationRelativeTo(null);
		setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
		setBounds(100, 100, 221, 209);
		
		contentPane = new JPanel();
		contentPane.setBorder(new EmptyBorder(5, 5, 5, 5));
		setContentPane(contentPane);
		contentPane.setLayout(null);
		
		
		lblLogin.setBounds(48, 39, 83, 13);
		contentPane.add(lblLogin);
		
		textFieldId = new JTextField();
		textFieldId.setBounds(48, 61, 96, 19);
		contentPane.add(textFieldId);
		textFieldId.setColumns(10);
		
		btnLogin.addActionListener(new LoginActionListener());
		
				
		btnLogin.setBounds(48, 92, 91, 21);
		contentPane.add(btnLogin);
		
	}
	
	//ログインボタンlistener
	class LoginActionListener implements ActionListener{
		@Override
		public void actionPerformed(ActionEvent e) {
			//idがあるか確認
			String id = textFieldId.getText();
			
			//　Player判別して、権限付与
			if(id.equals(MainStart.idPlayer1)) {
				MainStart.access = Access.PLAYER1;
				
			} else if(id.equals(MainStart.idPlayer2)) {
				MainStart.access = Access.PLAYER2;
				
			} else if(id.equals(MainStart.idPlayer3)) {
				MainStart.access = Access.PLAYER3;
				
			} else {
				MainStart.access = Access.TEMP;
				JOptionPane.showMessageDialog(null, "IDがありません。\nゲームは可能ですが、記録は残りません。");
			}
			
			//ゲーム画面に移動
			setVisible(false);			
			MainStart.frameGame.setVisible(true);
			
		}
	}
	
	
	
	
}
