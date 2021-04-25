import javax.swing.JFrame;

public class MainStart {
	
	public static JFrame frameLogin;
	public static JFrame frameGame;
	
	//player判別用
	public static Access access;
	
	//　player id
	public static final String idPlayer1 = "a";
	public static final String idPlayer2 = "b";
	public static final String idPlayer3 = "c";
	
	//　正解までトライ数
	public static int tryCountPlayer1;
	public static int tryCountPlayer2;
	public static int tryCountPlayer3;
	
	public static void main(String[] args) {
		tryCountPlayer1 = tryCountPlayer2 = tryCountPlayer3 = 0;
		
		frameLogin = new FrameLogin();
		frameGame = new FrameGame();
		
		frameLogin.setVisible(true);
	}
}
