public class Pagination {

    private int totalRecords; //모든 게시물의 수
    private int totalPages; //모든 페이지 수
    private int startRecord; //레코드 시작번호
    private int recordSize; //한페이지의 게시물 수
    private int startPage; //페이지 시작번호
    private int endPage; //페이지 마지막 번호
    private int pageSize; //이동가능한 페이지 수
    private int nowPage; //현재 페이지 번호
    private boolean prevPage;
    private boolean nextPage;

    public Pagination(int totalRecords, int inputNowPage, int recordPerPage, int visiblePageSize){
        this.totalRecords = totalRecords;
        this.recordSize = recordPerPage;
        this.pageSize = visiblePageSize;
        this.totalPages = (int) Math.ceil((double)totalRecords / recordSize);
        setNowPage(inputNowPage);


        if(totalRecords <= 0){
            this.startRecord = 0;
            this.startPage = 0;
            this.endPage = 0;
            this.prevPage = false;
            this.nextPage = false;

        } else {
            this.startRecord = (nowPage - 1) * recordSize + 1;
            this.startPage = setStartPage();
            this.endPage = setEndPage();
            this.prevPage = setPrevPage();
            this.nextPage = setNextPage();
        }
    }

    public int setStartPage() {
        int startPage = nowPage -  (pageSize / 2);
        if(startPage < 1){
            startPage = 1;
        }
        return startPage;
    }

    public int setEndPage() {
      endPage = startPage + pageSize - 1;
      if(endPage > totalPages){
          endPage = totalPages;
      }
      // 마지막 페이지 부근에서 페이지 수만큼 페이지블록을 보여주기 위해
      while(totalPages > pageSize && pageSize != (endPage - startPage + 1)){
          startPage--;
      }
      return endPage;
    }

    public void setNowPage(int nowPage) {
        this.nowPage = nowPage;
        if(nowPage < 1 || (nowPage > totalPages)){
            this.nowPage = 1;
        }
    }

    public int getNowPage() {
        return nowPage;
    }

    public boolean setPrevPage() {
        if(nowPage == 1){
            return false;
        }
        return true;
    }

    public boolean setNextPage() {
        if(nowPage == totalPages){
            return false;
        }
        return true;
    }

    public int getStartPage() {
        return startPage;
    }

    public int getEndPage() {
        return endPage;
    }

    public boolean isPrevPage() {
        return prevPage;
    }

    public boolean isNextPage() {
        return nextPage;
    }

    public int getTotalPages() {
        return totalPages;
    }

    public int getRecordSize() {
        return recordSize;
    }

    @Override
    public String toString() {
        return "Pagination{" +
                "totalRecords=" + totalRecords +
                ", totalPages=" + totalPages +
                ", startRecord=" + startRecord +
                ", recordSize=" + recordSize +
                ", startPage=" + startPage +
                ", endPage=" + endPage +
                ", pageSize=" + pageSize +
                ", nowPage=" + nowPage +
                ", prevPage=" + prevPage +
                ", nextPage=" + nextPage +
                '}';
    }
}
