import java.util.HashSet;



public class GroupWordChecker{

//그룹 단어 체커 (연속된 문자의 경우만 true, 같은문자가 연속되지 않게 나타나면 false)
public static boolean checker(String str) {
			HashSet<Character> pastLetters = new HashSet<>();
			for (int i = 0; i < str.length(); i++) {
				char ch = str.charAt(i);
				if(pastLetters.contains(ch)) {
					if(str.charAt(i - 1)  != ch) {
						return false;
					}
				} else {
					pastLetters.add(ch);
				}
			}
			return true;
		}


}
