import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.util.Arrays;
	
	public class PyramidFor {
		public static void main(String[] args) throws IOException{
			BufferedReader br = new BufferedReader(new InputStreamReader(System.in));
			BufferedWriter bw = new BufferedWriter(new OutputStreamWriter(System.out));
			
			int num = Integer.parseInt(br.readLine());
			int row = (2* num) - 1;
			int half = row / 2;
			int m=0;
			int t;
			
			for (int i = 0; i < row; i++) {
				// first to half
				if(i <= half) {
					// left blank
					for(int j = 1; j <= i; j++) {
						System.out.print(" ");
					}
					//stars
					for(int k = row - (2 *  i); k > 0; k--) {
						System.out.print("*");
					}
				// half+1 to last	
				} else {
					//left blank
					m++;
					t =  i - (2 * m);
					for (int p=0; p < i - (2 * m); p++) {
						System.out.print(" ");
					}
					//stars
					for (int s = 0; s < row - (2*t); s++) {
						System.out.print("*");
					}
				}
				System.out.println();
			}
			
			
			
		}
	}
