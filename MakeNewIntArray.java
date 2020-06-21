public class MakeNewIntArray{

    /**
		 * Make new duplicated int array
		 * @param n size of array
		 * @return int array
		 */
		private static int[] makeNoDuplArray(int n) {
			int[] resultrray = new int[n];
			for(int i = 0; i < resultrray.length; i++) {
				int q = makeRandom();
				if(!checkExistedInArray(resultrray, q)) {
					resultrray[i] = q;
				} else {
					i--;
				}
			}
			return resultrray;
		}
}
