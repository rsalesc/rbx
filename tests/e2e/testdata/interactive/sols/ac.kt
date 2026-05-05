import java.util.*

fun main() {
    val scanner = Scanner(System.`in`)
    val n = scanner.nextLine().toInt()
    var lf = 1
    var rg = n + 1
    
    while (lf + 1 < rg) {
        val mid = (lf + rg) / 2
        println(mid)
        System.out.flush()
        
        if (scanner.nextLine() == "<") {
            rg = mid
        } else {
            lf = mid
        }
    }
    
    println("! $lf")
}
