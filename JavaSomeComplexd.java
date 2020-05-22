
import java.util.Arrays;
import java.util.ArrayList;

/**
 * 配列から平均、標準偏差、中央値、最頻値を求めて、表示するクラス
 * @author ジンドビン
 */
public class JavaSomeComplexd{

	public static void main(String[] args){
		int total = 0;
		double average = 0;
		int[] rdArray = new int[200];

		//配列に0～100をランダムに代入
		for(int i=0; i<rdArray.length; i++){
			rdArray[i] = (int)(Math.random() * 101);
		}
		//配列を表示
		showArray(rdArray);
		System.out.println("\n");
		//平均を求める
		average = getAverageInArray(rdArray);
		System.out.println("平均値は" + average + "です。");
		//標準偏差を求める
		double stdDeviation = getStandardDeviation(rdArray);
		System.out.println("標準偏差は" + stdDeviation + "です。");
		//中央値を求める
		double median = getMedianInArray(rdArray);
		System.out.println("中央値は"+ median + "です。");
		//最頻値を求める
		int mode = getModeInArray(rdArray);
		System.out.println("最頻値は" + mode + "です。");
		
	}

	// 配列を表示
	private static void showArray(int[] array){
		
		for(int i=0; i < array.length; i++){

			if(i % 10 == 0 && i != 0){
				System.out.println();
			}
			System.out.print(array[i] + " ");
			
			
		}
		System.out.println();
	}
	
	//配列の平均を求めるメソッド
	private static double getAverageInArray(int[] array){
		int sum = 0;
		double average = 0;
		for(int i=0; i < array.length; i++){
			sum += array[i];
		}
		average = (double) sum / array.length;
		return average;
	}
	//配列の標準偏差を求めるメソッド
	private static double getStandardDeviation(int[] array){
		// 配列の平均
		double average = getAverageInArray(array);
		// 偏差
		double deviation = 0;
		// 偏差の二乗
		double squaredDeviation = 0;
		// 偏差の合計
		double sumOfSquaredDeviation = 0;
		//分散
		double variance = 0;
		
		// 全偏差の2乗の合計を求める
		for(int i=0; i < array.length; i++){
			deviation = (array[i] - average);
			squaredDeviation = deviation * deviation; 
			sumOfSquaredDeviation += squaredDeviation ;
		}
		variance = sumOfSquaredDeviation / array.length;
		return Math.sqrt(variance);
	}

	// 中央値お求めるメソッド
	private static double getMedianInArray(int[] array){
		Arrays.sort(array);
		int midIndex = array.length / 2;

		if(array.length % 2 == 0){
			return (array[midIndex - 1] + array[midIndex]) / 2.0;			
		
		} else{
			return (double)array[midIndex];
		}
	}
	/** 
	 * 最頻値を求めるメソッド
	 * 配列から重複ない要素だけ数えた大きさで新しいリストを作る
	 * 中身を配列の重複なく、順序ある要素にする
	 * このリストと頻度数配列のindexは対応
	 * @param array 最頻値を求める配列
	 */ 
	private static int getModeInArray(int[] array){
		
		// 重複なしで、整列された要素のArrayList生成
		ArrayList<Integer> elementList = makeNoDuplicateArray(array);
		
		//頻度数を格納する配列
		int[] count = new int[elementList.size()];
		
		for(int arrIdx=0; arrIdx < array.length; arrIdx++){
			// 値があるインデックスを探す
			int index;
	
			// 頻度数を増やす場所を探す
			for(index=0; index < elementList.size(); index++){
				if(array[arrIdx] == elementList.get(index)){
					break;
				}
			}
			count[index]++;
		}
		//頻度数配列から最頻値のインデックスを得る
		int idx = getMaxIndex(count);

		//最頻値の値を返却
		return elementList.get(idx);
	}


	//配列から値が最大のとき、indexを求めるメソッド
	private static int getMaxIndex(int[] array){
		int max = array[0];
		int index = 0;
		for(int i=1; i < array.length; i++){
			if(array[i] > max){
				max = array[i];
				index = i;
			}
		}
		return index;
	}
	//配列から重複がなくて、ソートされたArrayList生成
	public static ArrayList<Integer> makeNoDuplicateArray(int[] array){
		
		Arrays.sort(array); 
		
		// 要素のArrayList　
		ArrayList<Integer> noDuplicatedList = new ArrayList<>();
		// 比較する前の値
		int before = array[0];
		//　最初の要素代入
		noDuplicatedList.add(before);
		
		//配列で前の値と違ったとき、Listに追加
		for(int i=1; i < array.length; i++){
			before = array[i-1];
			if(before != array[i]){
				noDuplicatedList.add(array[i]);
			}
		}
		return noDuplicatedList;
	}

}
