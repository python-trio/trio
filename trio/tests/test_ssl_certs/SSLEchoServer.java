/* Self-contained java SSL echo server useful for testing. Features:
 *
 *   - Picks an open port at startup and prints it to stdout.
 *   - Accepts one connection then exits when it's closed.
 *   - Every time it sees byte 0xff, it starts a renegotiation.
 *   - Fantastically inefficient (emits a new TLS frame for each output byte)
 *
 * Rebuild:
 *
 *   javac SSLEchoServer.java
 *
 * Usage:
 *
 *   java SSLEchoServer CERTFILE.pkcs12
 *
 * Example:
 *
 *   java SSLEchoServer trio-test-1.pkcs12
 *
 * The certificate is assumed to be stored in PKCS12 format, and to have the
 * password "trio". make-test-certs.sh will generate such files.
 *
 * Adding -Djavax.net.debug=ssl can be useful for debugging.
 */

import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLServerSocket;
import javax.net.ssl.SSLServerSocketFactory;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.IOException;

public class SSLEchoServer
{
    public static void main(String[] args) throws IOException {
        /* Extremely janky command line parsing */
        try {
            System.setProperty("javax.net.ssl.keyStore", args[0]);
        }
        catch (NumberFormatException|ArrayIndexOutOfBoundsException exc) {
            System.err.println("usage: SSLEchoServer CERTFILE.pkcs12");
            System.exit(1);
        }
        System.setProperty("javax.net.ssl.keyStorePassword", "trio");
        System.setProperty("javax.net.ssl.keyStoreType", "PKCS12");

        SSLServerSocketFactory ssf =
            (SSLServerSocketFactory) SSLServerSocketFactory.getDefault();
        SSLServerSocket ss =
            (SSLServerSocket) ssf.createServerSocket(0);

        System.out.println(ss.getLocalPort());

        SSLSocket s = (SSLSocket) ss.accept();

        InputStream is = s.getInputStream();
        OutputStream os = s.getOutputStream();

        while (true) {
            int b = is.read();

            if (b == -1) {
                // EOF
                return;
            }

            if (b == 0xff) {
                s.startHandshake();
            }

            os.write(b);
        }
    }
}
