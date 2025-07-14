import java.util.Scanner;

public class java_solution {
    public static void main(String[] args) {
        Scanner scanner = new Scanner(System.in);
        
        // Simple communication with interactor
        System.out.println("2");
        System.out.flush();
        
        System.out.println("hello");
        System.out.flush();
        String response1 = scanner.nextLine();
        System.err.println("Received: " + response1);
        
        System.out.println("java");
        System.out.flush();
        String response2 = scanner.nextLine();
        System.err.println("Received: " + response2);
        
        scanner.close();
    }
} 