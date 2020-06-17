<%@page import="java.util.Arrays"%>
<%@page import="java.net.URLDecoder"%>
<%@page import="studyb.UserInfo"%>
<%@page import="java.util.ArrayList"%>
<%@ page language="java" contentType="text/html; charset=UTF-8"
    pageEncoding="UTF-8"%>
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>B30_SELECT</title>
<link href= "css/B30_style.css" rel="stylesheet">
</head>
<body>

	<h1>検索画面</h1>
	<form action ="B30_SELECT" method="post">
		<table>
			<tbody>
				<tr>
					<td>表示内容</td>
					<td colspan="3">
						<label for="checked_testno">TESTNO</label>
						<input type="checkbox" name="show_what" value="testno" id="checked_testno" ${cookie.testnoStatus.value == 'no' ? '' : 'checked' }>
						<label for="checked_name">NAME</label>
						<input type="checkbox" name="show_what" value="name" id="checked_name" ${cookie.nameStatus.value == 'no' ? '' : 'checked' }>
						<label for="checked_kana">KANA</label>
						<input type="checkbox" name="show_what"  value="kana" id="checked_kana" ${cookie.kanaStatus.value == 'no' ? '' : 'checked' }>
					</td>
				</tr>
				<tr>
					<td>検索条件</td>
					<td colspan="3">
						<input type = "text" name="q" value="${cookie.q.value }">
						(NAME前方一致)
					</td>
				</tr>
				<tr>
					<td>ソート</td>
					<td colspan="3">
						<select name="order_std">
						  <option value="std_testno" ${cookie.order_std.value == 'std_testno' ? 'selected' : ''}>TESTNO</option>
						  <option value="std_name" ${cookie.order_std.value == 'std_name' ? 'selected' : ''}>NAME</option>
						  <option value="std_kana" ${cookie.order_std.value == 'std_kana' ? 'selected' : ''}>KANA</option>
						</select>
						<input type="radio" name="order" value="up" id="order_up" checked>
						<label for="order_up">昇順</label>
						<input type="radio" name="order" value="down" id="order_down" ${cookie.order.value == 'down' ? 'checked'  : ''}>
						<label for="order_down">降順</label>
					</td>
				</tr>
			</tbody>
		</table>
		<br>
		<input type="submit" value="検索">
	</form>
	<hr>

			<%--検索結果 --%>
			<%
			if(session.getAttribute("searchResult") != null){
				Object obj = session.getAttribute("searchResult");
				
				if(obj instanceof ArrayList){
					ArrayList<UserInfo> users = (ArrayList)obj;
					
					out.println("<table id='resultTable'>");
					out.println("<thead><tr>");
					out.println("<td>TESTNO</td><td>NAME</td><td>KANA</td>");
					out.println("</thead></tr>");
					out.println("<tbody>");
					
					//userをテーブルに出力
					for(UserInfo user : users){
						out.println("<tr>");
						
						//TESTNOフィールド
						out.print("<td>"); 
						if(user.getTestNo() != 0){
							out.print(String.valueOf(user.getTestNo()));
						}
						out.print("</td>");
						
						// NAMEフィールド
						out.print("<td>"); 
						if(user.getName() != null){
							out.print(String.valueOf(user.getName()));
						}
						out.print("</td>");
						
						// KANAフィールド
						out.print("<td>"); 
						if(user.getKana() != null){
							out.print(String.valueOf(user.getKana()));
						}
						out.print("</td>");
						
						
						out.println("</tr>");
					}
					
					out.println("</tbody></table>");
				}
				session.invalidate();
			//検索結果がない場合
			} else{
				out.println("<h4>No Users</h4>");
			}
			
			%>

</body>
</html>
