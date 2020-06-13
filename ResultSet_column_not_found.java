/*
 * ResultSet에 존재하는 칼럼에 맞춰 user객체에 세팅  
 * Column 'xxx' not found 를 방지
 * rs.getParameter("비존재 칼럼")을 해결하는 방법
 */

// ResultSetの情報
		ResultSetMetaData meta = rs.getMetaData();
		int columnCount = meta.getColumnCount();
		
		while(rs.next()) {
			UserInfo user = new UserInfo();
			// 存在するCOLUMNに合わせて、userに情報格納
			for(int i = 1; i <= columnCount; i++) {
				String columnName = meta.getColumnName(i);
				switch (columnName) {
				
				case "TESTNO":
					user.setTestNo(rs.getInt(i));
					break;
					
				case "NAME":
					user.setName(rs.getString(i));
					break;
					
				case "KANA":
					user.setKana(rs.getString(i));
					break;

				default:
					System.out.println("no column name" + columnName);
					break;
				}
			}
			//userを結果のListに追加
			list.add(user);
		}
