package smallA;

import java.util.HashMap;
import java.util.Map;

public class ChCount {

	public static void main(String[] args) {
		//to lower case
		String a = "Hello World30020";

		System.out.println(toLower(a));
		Map<String, Integer> map = count(a);
		
		for (Map.Entry<String, Integer> entry : map.entrySet()) {
		    System.out.println("Key = " + entry.getKey() + ", Value = " + entry.getValue());
		}
		

	}
	//make the all letters to lower case
	public static String toLower(String str) {
		
		String answer = "";
		for(char c : str.toCharArray()) {
			
			if(Character.isUpperCase(c)) {
				answer += (char)(c + 32);
				
			} else {
				answer += c;
			}
		}
				
		return answer;
	}
	
	// count number of lowerCase, upperCase, numbers in the string
	public static Map<String, Integer> count(String str){
		
		int lowCharCount = 0;
		int upCharCount = 0;
		int numCount = 0;
		
		for(char c : str.toCharArray()) {
			if(Character.isLowerCase(c)) {
				lowCharCount++;
			} else if(Character.isUpperCase(c)) {
				upCharCount++;
			} else if(Character.isDigit(c)) {
				numCount++;
			}
		}
		
		Map<String, Integer> result = new HashMap<>();
		result.put("lowCharCount", lowCharCount);
		result.put("upCharCount", upCharCount);
		result.put("numCount", numCount);
		
		
		
		return result;
	}

}
