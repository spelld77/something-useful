package smallA;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.util.ArrayList;


public class StackPractice {
	public static void main(String[] args) throws NumberFormatException, IOException{
//		정수를 저장하는 스택을 구현한 다음, 입력으로 주어지는 명령을 처리하는 프로그램을 작성하시오.
//
//		명령은 총 다섯 가지이다.
//
//		push X: 정수 X를 스택에 넣는 연산이다.
//		pop: 스택에서 가장 위에 있는 정수를 빼고, 그 수를 출력한다. 만약 스택에 들어있는 정수가 없는 경우에는 -1을 출력한다.
//		size: 스택에 들어있는 정수의 개수를 출력한다.
//		empty: 스택이 비어있으면 1, 아니면 0을 출력한다.
//		top: 스택의 가장 위에 있는 정수를 출력한다. 만약 스택에 들어있는 정수가 없는 경우에는 -1을 출력한다.
		
		BufferedReader br = new BufferedReader(new InputStreamReader(System.in));
		int cmdCount = Integer.parseInt(br.readLine());
		
		Stack stack = new StackImpl();
		
		for (int i = 0; i < cmdCount; i++) {
			String cmdAll = br.readLine();
			String[] cmdFragments = cmdAll.split(" ");

			//push
			if (cmdFragments[0].equals("push")) {
				int num = Integer.parseInt(cmdFragments[1]);
				stack.push(num);
				continue;
			}
			//except push
			switch (cmdFragments[0]) {
			case "pop":
				System.out.println(stack.pop());
				break;

			case "size":
				System.out.println(stack.size());
				break;
			case "empty":
				System.out.println(stack.empty());
				break;							
			case "top":
				System.out.println(stack.top());
				break;
			default:
				break;
			}

			
			
		}
		
		
	}
}

class StackImpl implements Stack{

	ArrayList<Integer> stack = new ArrayList<Integer>();
	int top = -1;
	int size = 0;
	
	@Override
	public void push(int num) {
		stack.add(num);
		top++;
		size++;
		
	}

	@Override
	public int pop() {
		if (top == -1) {
			return -1;
		}
		int toReturn = stack.get(top);
		stack.remove(top);
		top--;
		size--;
		return toReturn;
	}

	@Override
	public int size() {
		return size;
	}

	@Override
	public int empty() {
		if (size == 0) {
			return 1;
		}
		return 0;
	}

	@Override
	public int top() {
		if (top == -1) {
			return -1;
		}
		return stack.get(top);
	}
	
}

interface Stack{
	void push(int num);
	int pop();
	int size();
	int empty();
	int top();
}
