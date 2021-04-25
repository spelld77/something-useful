import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;

import javax.swing.JButton;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JOptionPane;
import javax.swing.JPanel;
import javax.swing.JTextArea;
import javax.swing.JTextField;
import javax.swing.border.EmptyBorder;

public class FrameGame extends JFrame {

	private JPanel contentPane;
	private JTextField textFieldInput;
	private JTextField textFieldComment;
	private JLabel lblTryCountPlayer1;
	private JLabel lblTryCountPlayer2;
	private JLabel lblTryCountPlayer3;
	
	//正解の数がはいているList
//	private List<Integer> answerList;
	
	//正解の配列
	private int[] answerArr;
	
	//トライした回数
	private int numOfTry;


	/**
	 * Create the frame.
	 */
	public FrameGame() {
		setTitle("Game");
		setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
		setBounds(100, 100, 450, 300);
		contentPane = new JPanel();
		contentPane.setBorder(new EmptyBorder(5, 5, 5, 5));
		setContentPane(contentPane);
		contentPane.setLayout(null);
		
		JTextArea textArea = new JTextArea();
		textArea.setEditable(false);
		textArea.setText("３つの数字を探す。\r\n入力値と比べて位置と数字が一致していれば2点\r\n位置は違うが数字が一致していれば1点\r\nただし、数字に重複はない。");
		
		textArea.setBounds(49, 21, 334, 82);
		contentPane.add(textArea);
		
		JButton btnTry = new JButton("Try");
		btnTry.setBounds(165, 131, 56, 21);
		btnTry.addActionListener(new BtnTryAction());
		contentPane.add(btnTry);
		
		textFieldInput = new JTextField();
		textFieldInput.setBounds(64, 132, 96, 19);
		contentPane.add(textFieldInput);
		textFieldInput.setColumns(10);
		
		JButton btnBack = new JButton("Back");
		btnBack.addActionListener(new ActionListener() {
			public void actionPerformed(ActionEvent e) {
				
				MainStart.frameLogin.setVisible(true);
				MainStart.frameGame.dispose();
				MainStart.frameGame = new FrameGame();
				MainStart.frameGame.setVisible(false);
				
			}
		});
		btnBack.setBounds(301, 131, 65, 21);
		contentPane.add(btnBack);
		
		textFieldComment = new JTextField();
		textFieldComment.setEditable(false);
		textFieldComment.setBounds(64, 180, 302, 19);
		contentPane.add(textFieldComment);
		textFieldComment.setColumns(10);
		
		JButton btnReset = new JButton("Reset");
		btnReset.addActionListener(new ActionListener() {
			public void actionPerformed(ActionEvent e) {
				textFieldInput.setText(null);
				textFieldComment.setText(null);
				numOfTry = 0;
				answerArr = makeThreeNum();
			}
		});
		btnReset.setBounds(224, 131, 71, 21);
		contentPane.add(btnReset);
		
		JLabel lblPlayer1 = new JLabel("Player1");
		lblPlayer1.setBounds(98, 209, 50, 13);
		contentPane.add(lblPlayer1);
		
		JLabel lblPlayer2 = new JLabel("Player2");
		lblPlayer2.setBounds(195, 209, 50, 13);
		contentPane.add(lblPlayer2);
		
		JLabel lblPlayer3 = new JLabel("Player3");
		lblPlayer3.setBounds(287, 209, 50, 13);
		contentPane.add(lblPlayer3);
		
		lblTryCountPlayer1 = new JLabel(String.valueOf(MainStart.tryCountPlayer1));
		lblTryCountPlayer1.setBounds(108, 232, 36, 13);
		contentPane.add(lblTryCountPlayer1);
		
		lblTryCountPlayer2 = new JLabel(String.valueOf(MainStart.tryCountPlayer2));
		lblTryCountPlayer2.setBounds(205, 232, 36, 13);
		contentPane.add(lblTryCountPlayer2);
		
		lblTryCountPlayer3 = new JLabel(String.valueOf(MainStart.tryCountPlayer3));
		lblTryCountPlayer3.setBounds(301, 232, 36, 13);
		contentPane.add(lblTryCountPlayer3);
		
		JLabel lblNumOfTry = new JLabel("何回で成功?");
		lblNumOfTry.setBounds(12, 232, 89, 13);
		contentPane.add(lblNumOfTry);
		
		//ランダム数字生成
		answerArr = makeThreeNum();
	}


	
	//TRYボタン
	class BtnTryAction implements ActionListener{
		@Override
		public void actionPerformed(ActionEvent e) {	
			
			int score = 0;
			numOfTry++;
			
			String userStr= textFieldInput.getText();
			
			//3桁以外は処理しない
			if(userStr.length() != 3) {
				JOptionPane.showMessageDialog(null, "数字を3桁で力してください。");
				return;
			}
			
			//ユーザが入力した数
			int[] inputNums = new int[3];		
			try {
				inputNums[0] = Integer.parseInt(userStr.substring(0, 1));
				inputNums[1] = Integer.parseInt(userStr.substring(1, 2));
				inputNums[2] = Integer.parseInt(userStr.substring(2, 3));
			} catch (Exception e2) {
				e2.printStackTrace();
				JOptionPane.showMessageDialog(null, "数字を入力してください");
				return;
			}
			
			//点数集計			
			for(int i = 0; i < answerArr.length; i++) {
				//正解の数一つ
				int answerNum = answerArr[i];
				
				//正解数がユーザの答にあるか、位置が正しいか調査
				for(int j = 0; j < inputNums.length; j++) {
					//正解数がユーザの答にあるとき
					if(answerNum == inputNums[j]) {
						score++;
						//位置が同じ場合
						if(i == j) {
							score++;
						}
						break;
					}
				}
			}
			
			//点数を表示
			String comment = "あなたの点数は「" + score + "」点です。";
			textFieldComment.setText(comment);
			
			//正解確認用
//			System.out.println("answer.;; " + answerArr[0]+answerArr[1]+answerArr[2]);
			
			//6点（正解）の場合、正解までいくつ掛かったか表示
			if(score >= 6) {
				//　トライ回数
				String tryCount = String.valueOf(numOfTry);
				// Player区分
				Access access = MainStart.access;
				
				//点数を記録、表示
				if(access == Access.PLAYER1) {
					lblTryCountPlayer1.setText(tryCount);
					MainStart.tryCountPlayer1 = numOfTry;
					
				} else if(access == Access.PLAYER2) {
					lblTryCountPlayer2.setText(tryCount);
					MainStart.tryCountPlayer2 = numOfTry;
					
				} else if(access == Access.PLAYER3) {
					lblTryCountPlayer3.setText(tryCount);
					MainStart.tryCountPlayer3 = numOfTry;
				}
				
				JOptionPane.showMessageDialog(null, "正解です。");
				
				//　random数字、トライ数初期化
				answerArr = makeThreeNum();
				numOfTry = 0;
			}
		}
	}
	
		//　0-9で3個の数が入る配列を生成（重複なし）
		private int[] makeThreeNum(){
			
			int[] result = {-1, -1, -1};
			int randNum =  -1;
			//重複可否
			boolean duplicated;
			
			for(int i = 0; i < 3; i++) {
				
				duplicated = false;
				randNum =  (int)(Math.random() * 10);
				
				//前の値と比較
				for(int j = 0; j < i; j++) {
					//配列に存在する数の場合
					if(randNum == result[j]) {
						i--;
						duplicated = true;
						break;
					}
				}
				//重複無の場合、配列に数入力
				if(duplicated == false) {
					result[i] = randNum;
				}
			}
			return result;
		}
	
//	//0-9の数字3個（重複なし）を生成
//	private List<Integer> makeThreeNum(){
//	
//		ArrayList<Integer> result = new ArrayList<>();
//		//最初のrandom number
//		result.add((int)(Math.random() * 10));
//		
//		for(int i = 0; i < 2; i++) {
//			
//			// 0-9までの数字の一つ
//			int number = (int)(Math.random() * 10);
//			
//			//同じ数が出ない時まで繰り返し
//			for(int j = 0; j < result.size(); j++) {
//				if(number == result.get(j)) {
//					i--;
//					break;
//				}
//				//重複なしのとき、Listに追加
//				if(j == result.size()-1) {
//					result.add(number);
//					break;
//				}
//			}
//			
//			
//		}
//		//開発用
////		ArrayList<Integer> temp = new ArrayList<>();
////		temp.add(1);
////		temp.add(2);
////		temp.add(3);
////		return temp;
//		
//		return result;
//		
//	}
	
	
}
