import java.util.*;
import java.io.*;
 
public class Main {
	public static void main(String[] args) {
		Scanner in = new Scanner(System.in);
		int n = Integer.parseInt(in.nextLine());
		int lf = 1, rg = n + 1;
		while (lf + 1 < rg) {
			int mid = (lf + rg) / 2;
			System.out.println(mid+n);
			System.out.flush();
			if (in.nextLine().equals("<"))
				rg = mid;
			else
				lf = mid;	
		}
		System.out.println("! " + lf);
	}
}