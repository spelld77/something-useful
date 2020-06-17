package studyb;

import java.io.IOException;
import java.io.PrintWriter;
import java.net.URLEncoder;
import java.sql.SQLException;
import java.text.MessageFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import javax.servlet.RequestDispatcher;
import javax.servlet.ServletException;
import javax.servlet.annotation.WebServlet;
import javax.servlet.http.Cookie;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import javax.servlet.http.HttpSession;

/**
 * Servlet implementation class B30_SELECT
 */
@WebServlet("/B30_SELECT")
public class B30_SELECT extends HttpServlet {
	private static final long serialVersionUID = 1L;
       
    /**
     * @see HttpServlet#HttpServlet()
     */
    public B30_SELECT() {
        super();
    }


	/**
	 * @see HttpServlet#doPost(HttpServletRequest request, HttpServletResponse response)
	 */
	protected void doPost(HttpServletRequest request, HttpServletResponse response) throws ServletException, IOException {
		request.setCharacterEncoding("UTF-8");

		// 表示内容の選択がないとき、アラートを上げて前の画面にもどる
		if(request.getParameter("show_what") == null) {
			response.setContentType("text/html; charset=UTF-8"); 
			PrintWriter out = response.getWriter();
			out.println("<html><head><script>");
			RequestDispatcher dispatcher = request.getRequestDispatcher("js/alertMessage.js");
			dispatcher.include(request, response);
			out.println("</script></head></html>");
			return;
		}
		// 表示するものの配列
		String[] showWhat = request.getParameterValues("show_what");
		// 表示するもの　(SQLに渡すもの）
		String toSelect = "";
		// 表示するもののStringを得る　「　string1, string2, string3　」
		toSelect =Arrays.toString(showWhat);
		toSelect = toSelect.substring(1, toSelect.length() - 1);
		//検索条件（NAME）
		String q = request.getParameter("q").trim();

		//ソートの基準
		String orderStd = request.getParameter("order_std");
		if(orderStd.equals("std_testno")) {
			orderStd = "TESTNO";
		} else if(orderStd.equals("std_name")) {
			orderStd = "NAME";
		} else if(orderStd.equals("std_kana")) {
			orderStd = "KANA";
		} else {
			orderStd = "";
		}
		//ソートの方向
		String order = request.getParameter("order");
		if(order.equals("up")) {
			order = "ASC";
		} else if(order.equals("down")) {
			order = "DESC";
		} else {
			order="";
		}
		
		try(var db = new B14_DBAccess()) {
			db.connect();

			List<UserInfo> users = db.selectExec(toSelect, q, orderStd, order);
			// 検索結果があるとき、sessionに格納
			
			HttpSession session= request.getSession();
			if(users.size() != 0) {	
				session.setAttribute("searchResult", users);
			} else {
				session.invalidate();
			}

			// 選択した表示内容checkbox
			String testnoStatus="no";
			String nameStatus="no";
			String kanatStatus="no";
			// 前に選択したらyesにする
			for(String s : showWhat) {
				switch(s) {
				case "testno":
					testnoStatus = "yes";
					break;
				case "name":
					nameStatus = "yes";
					break;
				case "kana":
					kanatStatus ="yes";
					break;
				}
			}
			//入力した formタグの保持のため
			Cookie[] coo = {			
					new Cookie("testnoStatus", testnoStatus ),
					new Cookie("nameStatus", nameStatus ),
					new Cookie("kanaStatus",  kanatStatus ),
					new Cookie("q", request.getParameter("q")),
					new Cookie("order_std", request.getParameter("order_std")),
					new Cookie("order", request.getParameter("order"))
			};
			for(Cookie cookie : coo) {
				cookie.setMaxAge(3);
				response.addCookie(cookie);
			}
			
			 response.sendRedirect("B30_SELECT.jsp");
			
		} catch(ClassNotFoundException e) {
			e.printStackTrace();
			
		} catch (SQLException e) {
			e.printStackTrace();
		}
		
	
	}

}
