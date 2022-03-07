public class MyLinkedList {
	public static void main(String[] args) {
		LinkedLi<String> myList = new LinkedLi<>();
		myList.addFirst("element 1");
		myList.addFirst("element 2");
		myList.addFirst("element 3");
		myList.addLast("element 4");
		myList.addLast("element 5");
		myList.addLast("element 6");
		myList.reverseList();
		myList.removeElement("element 4");
		while(!myList.isEmpty()) {
			myList.removeFirst();
		}

	
	}
	

}

class LinkedLi<E>{

	private Node<E> head = null;
	private Node<E> tail = null;
	private int size = 0;
	
	public LinkedLi() {}
	public int size() {
		return size;
	}
	
	public boolean isEmpty() {
		return size == 0 ? true : false;
	}
	
	public E first() {
		if(isEmpty()) {
			return null;
		}
		return head.getData();
	}
	
	public E last() {
		if(isEmpty()) {
			return null;
		}
		return tail.getData();
	}
	
	public void addFirst(E e) {
		head = new Node<>(e, head);
		if(size == 0) {
			tail = head;
		}
		size++;
		System.out.println("Added head node with'" + head.getData() + "' element");
	}
	
	public void addLast(E e) {
		Node<E> newNode = new Node<E>(e, null);
		if(isEmpty()) {
			head = newNode;
		} else {
			tail.setNextNode(newNode);
		}
		tail = newNode;
		size++;
		System.out.println("Added tail node with'" + tail.getData() + "' element");
	}
	
	public E removeFirst() {
		if(isEmpty()) {
			return null;
		}
		E answer = head.getData();
		head = head.getNextNode();
		size--;
		if(size == 0) {
			tail = null;
		}
		System.out.println("Removed head node with'" + answer + "' element");
		return answer;
	}
	
	public void reverseList() {
		if(size <= 1) {
			
		} else if(size == 2) {
			tail.setNextNode(head);
			head = tail;
			tail = head.getNextNode();
			tail.setNextNode(null);
		} else {
			Node<E> current = head;
			Node<E> currentNext = head.getNextNode();
			Node<E> currentNextNext = currentNext.getNextNode();
			
			tail = head;
			while(currentNext != null) {
				currentNext.setNextNode(current);
				current = currentNext;
				currentNext = currentNextNext;
				if(currentNextNext != null) {
					currentNextNext = currentNextNext.getNextNode();
				}
			}
			tail.setNextNode(null);
			head = current;
		}
	}
	
	public E removeElement(E e) {
		Node<E> current = head;
		Node<E> previous = head;
		int position = 0;
		while(current != null && current.getData() != e) {
			previous = current;
			current = current.getNextNode();
			position++;
		}
		if(current == null) {
			return null;
		} else {
			if(head == current) {
				head = current.getNextNode();
			} else if(tail == current){
				tail = previous;
				tail.setNextNode(null);
			} else {
				previous.setNextNode(current.getNextNode());
			}
			System.out.println("Found & removed node at position " + position);
			size--;
			return current.getData();
		}
	}
	
	
	
}


class Node<E>{
	
	E data;
	Node<E> next;
	
	
	public Node(E data, Node<E> next) {
		this.data = data;
		this.next = next;
	}
	
	public E getData() {
		return data;
	}
	public Node<E> getNextNode() {
		return next;
	}
	public void setNextNode(Node<E> n) {
		next = n;
	}
}
